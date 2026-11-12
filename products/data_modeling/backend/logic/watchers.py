"""Who watches a DAG node for failure notifications.

The creator of a saved query watches that query's node without a stored row. Any user can watch a
node by storing a `subscribed=True` row, and the creator stops watching by storing a
`subscribed=False` row. A node with no creator has no default watcher: a node that is not backed by
a saved query, a managed viewset, or a creator whose user was deleted.
"""

from collections.abc import Collection
from uuid import UUID

from django.db.models import Q

from posthog.models import Team, User

from products.data_modeling.backend.facade.contracts import UnknownNodeError
from products.data_modeling.backend.models.node import Node
from products.data_modeling.backend.models.node_subscription import NodeSubscription


def _live_nodes(team_id: int):
    return Node.objects.filter(team_id=team_id).exclude(saved_query__deleted=True)


def watcher_user_ids(team_id: int, node_id: UUID) -> frozenset[int]:
    """The active users with access to the team who watch this node.

    This does not check per-object access to the node's saved query. The caller that sends the
    notification must drop users who cannot read it.
    """
    node = _live_nodes(team_id).filter(id=node_id).values("saved_query__created_by_id").first()
    if node is None:
        return frozenset()

    subscribed_by_user = dict(
        NodeSubscription.objects.for_team(team_id).filter(node_id=node_id).values_list("user_id", "subscribed")
    )
    candidate_ids = {user_id for user_id, subscribed in subscribed_by_user.items() if subscribed}
    creator_id = node["saved_query__created_by_id"]
    if creator_id is not None and subscribed_by_user.get(creator_id, True):
        candidate_ids.add(creator_id)
    if not candidate_ids:
        return frozenset()

    candidate_uuids = [str(uuid) for uuid in User.objects.filter(id__in=candidate_ids).values_list("uuid", flat=True)]
    team = Team.objects.get(id=team_id)
    return frozenset(team.all_users_with_access(user_uuids=candidate_uuids).values_list("id", flat=True))


def set_watching(team_id: int, node_id: UUID, user_id: int, watching: bool) -> None:
    if not _live_nodes(team_id).filter(id=node_id).exists():
        raise UnknownNodeError(f"Node {node_id} not found")
    NodeSubscription.objects.for_team(team_id).update_or_create(
        node_id=node_id,
        user_id=user_id,
        defaults={"subscribed": watching},
        create_defaults={"team_id": team_id, "subscribed": watching},
    )


def watched_node_ids(team_id: int, user_id: int, node_ids: Collection[UUID]) -> frozenset[UUID]:
    """The live nodes among `node_ids` that this user watches, by a stored row or as the creator."""
    user_rows = NodeSubscription.objects.for_team(team_id).filter(user_id=user_id)
    watched = Q(id__in=user_rows.filter(subscribed=True).values("node_id")) | (
        Q(saved_query__created_by_id=user_id) & ~Q(id__in=user_rows.filter(subscribed=False).values("node_id"))
    )
    return frozenset(_live_nodes(team_id).filter(id__in=node_ids).filter(watched).values_list("id", flat=True))
