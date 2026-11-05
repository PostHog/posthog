"""The silent checks before a command reaches the shared steps, as one policy for every channel.

A channel calls these with its own rollout flag and its own keys, and decides what else it checks.
"""

from collections.abc import Collection

from django.core.cache import cache

import structlog

from posthog.models.team import Team
from posthog.permissions import posthog_feature_flag_enabled
from posthog.token_bucket import BucketDecision, Budget, consume

from .commands import DispatchOutcome, SubjectRef
from .subjects import candidate_team_ids, rollout_key

logger = structlog.get_logger(__name__)

_CLAIM_TTL_SECONDS = 7 * 24 * 60 * 60
# A person typing commands rarely sends more than a few in a row. The cap stops a script or a
# runaway agent with a member's account from fanning out runs that cost money.
_REQUESTER_BUDGET = Budget(burst=5, per_hour=30)


def rolled_out_team_ids(
    flag: str,
    subject: SubjectRef,
    organization_ids: Collection[str] | None = None,
    *,
    only_evaluate_locally: bool = False,
) -> tuple[int, ...]:
    """The subject's candidate projects whose organization is in the rollout, in the subject's order.

    ``organization_ids`` narrows them, for a channel that may reach only some organizations. A caller
    inside a webhook passes ``only_evaluate_locally``, so a flag that cannot be evaluated locally
    reads as off instead of costing a remote call per project.
    """
    team_ids = candidate_team_ids(subject)
    teams = Team.objects.filter(id__in=team_ids).only("id", "organization_id")
    if organization_ids is not None:
        teams = teams.filter(organization_id__in=organization_ids)
    distinct_id = f"{flag}-{rollout_key(subject)}"
    rolled_out = {
        team.id
        for team in teams
        if posthog_feature_flag_enabled(
            flag,
            # The rollout targets organizations, so the person behind the request does not matter yet.
            distinct_id,
            organization_id=team.organization_id,
            team_id=team.id,
            only_evaluate_locally=only_evaluate_locally,
        )
    }
    return tuple(team_id for team_id in team_ids if team_id in rolled_out)


def claim(key: str) -> DispatchOutcome | None:
    """None when this call claimed the request, else the outcome that stops dispatch."""
    try:
        claimed = cache.add(key, 1, timeout=_CLAIM_TTL_SECONDS)
    except Exception:
        # Fail closed: the cache shares Redis with the Celery broker, so an outage that drops this
        # command drops it anyway, while failing open lets a redelivery start a second paid run.
        logger.warning("command_claim_failed", key=key, exc_info=True)
        return "claim_unavailable"
    return None if claimed else "duplicate"


def release(key: str) -> None:
    try:
        cache.delete(key)
    except Exception:
        logger.warning("command_release_failed", key=key, exc_info=True)


def within_rate_limit(key: str) -> bool:
    decision = consume(key, _REQUESTER_BUDGET)
    # Fail open when Redis can't answer, like the other per-caller buckets.
    return not isinstance(decision, BucketDecision) or decision.allowed
