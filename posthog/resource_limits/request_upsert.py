from typing import TYPE_CHECKING

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

if TYPE_CHECKING:
    from posthog.models.limit_increase_request import LimitIncreaseRequest
    from posthog.models.team.team import Team
    from posthog.models.user import User


def upsert_limit_increase_request(
    *,
    team: "Team",
    limit_key: str,
    limit: int,
    current_count: int,
    user: "User | None",
) -> "LimitIncreaseRequest":
    """Create or bump a pending ``LimitIncreaseRequest`` for the given team/key.

    Dedup: at most one ``status=pending`` request per ``(team, limit_key)`` —
    enforced both here (``select_for_update`` + upsert branch) and at the DB
    layer (partial unique constraint on the model).
    """
    from posthog.models.limit_increase_request import LimitIncreaseRequest, LimitIncreaseRequestStatus

    def _bump(request: LimitIncreaseRequest) -> LimitIncreaseRequest:
        request.hit_count = F("hit_count") + 1
        request.last_hit_at = timezone.now()
        request.save(update_fields=["hit_count", "last_hit_at"])
        request.refresh_from_db()
        return request

    with transaction.atomic():
        existing = (
            LimitIncreaseRequest.objects.select_for_update()
            .filter(
                team_id=team.id,
                limit_key=limit_key,
                status=LimitIncreaseRequestStatus.PENDING,
            )
            .first()
        )
        if existing is not None:
            return _bump(existing)

        # No row to lock yet: two concurrent first-hits can both reach here and
        # race to INSERT. The partial unique constraint
        # ``one_pending_limit_increase_request_per_team_key`` makes the loser of
        # the race raise ``IntegrityError`` instead of creating a duplicate; we
        # catch it, re-read the row the winner just wrote, and fall through to
        # the bump branch.
        try:
            with transaction.atomic():
                return LimitIncreaseRequest.objects.create(
                    team=team,
                    limit_key=limit_key,
                    limit_at_first_hit=limit,
                    count_at_first_hit=current_count,
                    requested_by=user,
                    justification="",
                    status=LimitIncreaseRequestStatus.PENDING,
                )
        except IntegrityError:
            existing = LimitIncreaseRequest.objects.select_for_update().get(
                team_id=team.id,
                limit_key=limit_key,
                status=LimitIncreaseRequestStatus.PENDING,
            )
            return _bump(existing)
