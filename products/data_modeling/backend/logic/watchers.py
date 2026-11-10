"""Who watches a saved query (view) for failure notifications.

The creator of a view watches it without a stored row. Any user can watch a view by storing a
`subscribed=True` row, and the creator stops watching by storing a `subscribed=False` row. A view
with no creator (a managed viewset, or a creator whose user was deleted) has no default watcher.
"""

from uuid import UUID

from django.db.models import Q

from posthog.models import Team, User

from products.data_modeling.backend.facade.contracts import UnknownSavedQueryError
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.datawarehouse_saved_query_subscription import (
    DataWarehouseSavedQuerySubscription,
)


def _live_saved_queries(team_id: int):
    return DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True)


def watcher_user_ids(team_id: int, saved_query_id: UUID) -> frozenset[int]:
    """The active users with access to the team who watch this saved query.

    This does not check per-object access to the view itself. The caller that sends the
    notification must drop users who cannot read the view.
    """
    saved_query = _live_saved_queries(team_id).filter(id=saved_query_id).values("created_by_id").first()
    if saved_query is None:
        return frozenset()

    subscribed_by_user = dict(
        DataWarehouseSavedQuerySubscription.objects.for_team(team_id)
        .filter(saved_query_id=saved_query_id)
        .values_list("user_id", "subscribed")
    )
    candidate_ids = {user_id for user_id, subscribed in subscribed_by_user.items() if subscribed}
    creator_id = saved_query["created_by_id"]
    if creator_id is not None and subscribed_by_user.get(creator_id, True):
        candidate_ids.add(creator_id)
    if not candidate_ids:
        return frozenset()

    candidate_uuids = [str(uuid) for uuid in User.objects.filter(id__in=candidate_ids).values_list("uuid", flat=True)]
    team = Team.objects.get(id=team_id)
    return frozenset(team.all_users_with_access(user_uuids=candidate_uuids).values_list("id", flat=True))


def set_watching(team_id: int, saved_query_id: UUID, user_id: int, watching: bool) -> None:
    if not _live_saved_queries(team_id).filter(id=saved_query_id).exists():
        raise UnknownSavedQueryError(f"Saved query {saved_query_id} not found")
    DataWarehouseSavedQuerySubscription.objects.for_team(team_id).update_or_create(
        saved_query_id=saved_query_id,
        user_id=user_id,
        defaults={"subscribed": watching},
        create_defaults={"team_id": team_id, "subscribed": watching},
    )


def watched_saved_query_ids(team_id: int, user_id: int) -> frozenset[UUID]:
    """The live saved queries in the team that this user watches, by a stored row or as their creator."""
    user_rows = DataWarehouseSavedQuerySubscription.objects.for_team(team_id).filter(user_id=user_id)
    watched = Q(id__in=user_rows.filter(subscribed=True).values("saved_query_id")) | (
        Q(created_by_id=user_id) & ~Q(id__in=user_rows.filter(subscribed=False).values("saved_query_id"))
    )
    return frozenset(_live_saved_queries(team_id).filter(watched).values_list("id", flat=True))
