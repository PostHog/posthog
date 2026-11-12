from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Organization, Team, User

from products.data_modeling.backend.facade import api
from products.data_modeling.backend.facade.contracts import UnknownNodeError
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.models.node_subscription import NodeSubscription
from products.data_modeling.backend.test.helpers import metric_node


class TestWatchers(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.dag = DAG.get_or_create_default(self.team)
        self.users = {
            "creator": self.user,
            "member": self._create_user("member@example.com"),
            "inactive": self._create_user("inactive@example.com", is_active=False),
            "outsider": User.objects.create_and_join(
                Organization.objects.create(name="Other org"), "outsider@example.com", None
            ),
        }

    def _view_node(self, name: str = "view", creator: str | None = "creator", deleted: bool = False) -> Node:
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name=name,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            created_by=self.users[creator] if creator else None,
            deleted=deleted,
        )
        return Node.objects.create(team=self.team, dag=self.dag, saved_query=saved_query, type=NodeType.VIEW)

    @parameterized.expand(
        [
            ("creator_watches_by_default", "creator", [], {"creator"}),
            ("creator_opted_out", "creator", [("creator", False)], set()),
            ("non_creator_with_row", "creator", [("member", True)], {"creator", "member"}),
            ("non_creator_opt_out_row_is_no_row", "creator", [("member", False)], {"creator"}),
            ("no_creator_has_no_default_watcher", None, [], set()),
            ("no_creator_with_row", None, [("member", True)], {"member"}),
            ("inactive_user_excluded", "creator", [("inactive", True)], {"creator"}),
            ("user_without_team_access_excluded", "creator", [("outsider", True)], {"creator"}),
        ]
    )
    def test_watcher_user_ids(
        self, _name: str, creator: str | None, rows: list[tuple[str, bool]], expected: set[str]
    ) -> None:
        node = self._view_node(creator=creator)
        for user_key, subscribed in rows:
            NodeSubscription.objects.for_team(self.team.id).create(
                team_id=self.team.id, node=node, user=self.users[user_key], subscribed=subscribed
            )

        assert api.watcher_user_ids(self.team.id, node.id) == {self.users[key].id for key in expected}

    def test_node_without_saved_query_can_be_watched(self) -> None:
        node = metric_node(self.team, self.dag, "metric")
        assert api.watcher_user_ids(self.team.id, node.id) == frozenset()

        api.set_watching(self.team.id, node.id, self.users["member"].id, True)

        assert api.watcher_user_ids(self.team.id, node.id) == {self.users["member"].id}

    def test_set_watching_keeps_one_row_per_user_and_node(self) -> None:
        node = self._view_node()
        member = self.users["member"]

        api.set_watching(self.team.id, node.id, member.id, True)
        api.set_watching(self.team.id, node.id, member.id, True)
        assert api.watcher_user_ids(self.team.id, node.id) == {self.user.id, member.id}

        api.set_watching(self.team.id, node.id, self.user.id, False)
        api.set_watching(self.team.id, node.id, member.id, False)
        assert api.watcher_user_ids(self.team.id, node.id) == frozenset()

        api.set_watching(self.team.id, node.id, self.user.id, True)
        assert api.watcher_user_ids(self.team.id, node.id) == {self.user.id}
        assert NodeSubscription.objects.for_team(self.team.id).filter(node=node).count() == 2

    @parameterized.expand([("other_team",), ("deleted_saved_query",)])
    def test_set_watching_rejects_node_that_is_not_live_in_team(self, case: str) -> None:
        if case == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="Other team")
            node = metric_node(other_team, DAG.get_or_create_default(other_team), "metric")
        else:
            node = self._view_node(deleted=True)

        with self.assertRaises(UnknownNodeError):
            api.set_watching(self.team.id, node.id, self.user.id, True)
        assert not NodeSubscription.objects.unscoped().filter(node=node).exists()

    def test_watched_node_ids(self) -> None:
        member = self.users["member"]
        created = self._view_node("created")
        created_opted_out = self._view_node("created_opted_out")
        subscribed = self._view_node("subscribed", creator="member")
        not_subscribed = self._view_node("not_subscribed", creator="member")
        self._view_node("created_deleted", deleted=True)
        metric = metric_node(self.team, self.dag, "metric")
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        metric_node(other_team, DAG.get_or_create_default(other_team), "other_team_metric")

        api.set_watching(self.team.id, created_opted_out.id, self.user.id, False)
        api.set_watching(self.team.id, subscribed.id, self.user.id, True)
        api.set_watching(self.team.id, metric.id, self.user.id, True)

        all_ids = list(Node.objects.filter(team_id=self.team.id).values_list("id", flat=True))
        assert api.watched_node_ids(self.team.id, self.user.id, all_ids) == {created.id, subscribed.id, metric.id}
        assert api.watched_node_ids(self.team.id, member.id, all_ids) == {subscribed.id, not_subscribed.id}
        assert api.watched_node_ids(self.team.id, self.user.id, [created.id, not_subscribed.id]) == {created.id}
        assert api.watched_node_ids(self.team.id, self.user.id, []) == frozenset()
