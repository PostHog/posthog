from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Organization, Team, User

from products.data_modeling.backend.facade import api
from products.data_modeling.backend.facade.contracts import UnknownSavedQueryError
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.datawarehouse_saved_query_subscription import (
    DataWarehouseSavedQuerySubscription,
)


class TestWatchers(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.users = {
            "creator": self.user,
            "member": self._create_user("member@example.com"),
            "inactive": self._create_user("inactive@example.com", is_active=False),
            "outsider": User.objects.create_and_join(
                Organization.objects.create(name="Other org"), "outsider@example.com", None
            ),
        }

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
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="view", created_by=self.users[creator] if creator else None
        )
        for user_key, subscribed in rows:
            DataWarehouseSavedQuerySubscription.objects.for_team(self.team.id).create(
                team_id=self.team.id, saved_query=saved_query, user=self.users[user_key], subscribed=subscribed
            )

        assert api.watcher_user_ids(self.team.id, saved_query.id) == {self.users[key].id for key in expected}

    def test_set_watching_keeps_one_row_per_user_and_view(self) -> None:
        saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name="view", created_by=self.user)
        member = self.users["member"]

        api.set_watching(self.team.id, saved_query.id, member.id, True)
        api.set_watching(self.team.id, saved_query.id, member.id, True)
        assert api.watcher_user_ids(self.team.id, saved_query.id) == {self.user.id, member.id}

        api.set_watching(self.team.id, saved_query.id, self.user.id, False)
        api.set_watching(self.team.id, saved_query.id, member.id, False)
        assert api.watcher_user_ids(self.team.id, saved_query.id) == frozenset()

        api.set_watching(self.team.id, saved_query.id, self.user.id, True)
        assert api.watcher_user_ids(self.team.id, saved_query.id) == {self.user.id}
        assert (
            DataWarehouseSavedQuerySubscription.objects.for_team(self.team.id).filter(saved_query=saved_query).count()
            == 2
        )

    @parameterized.expand([("other_team",), ("deleted",)])
    def test_set_watching_rejects_saved_query_outside_team(self, case: str) -> None:
        if case == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="Other team")
            saved_query = DataWarehouseSavedQuery.objects.create(team=other_team, name="view")
        else:
            saved_query = DataWarehouseSavedQuery.objects.create(team=self.team, name="view", deleted=True)

        with self.assertRaises(UnknownSavedQueryError):
            api.set_watching(self.team.id, saved_query.id, self.user.id, True)
        assert not DataWarehouseSavedQuerySubscription.objects.unscoped().filter(saved_query=saved_query).exists()

    def test_watched_saved_query_ids(self) -> None:
        member = self.users["member"]

        def view(name: str, **kwargs) -> DataWarehouseSavedQuery:
            return DataWarehouseSavedQuery.objects.create(team=self.team, name=name, **kwargs)

        created = view("created", created_by=self.user)
        created_opted_out = view("created_opted_out", created_by=self.user)
        subscribed = view("subscribed", created_by=member)
        not_subscribed = view("not_subscribed", created_by=member)
        view("created_deleted", created_by=self.user, deleted=True)
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        DataWarehouseSavedQuery.objects.create(team=other_team, name="other_team", created_by=self.user)

        api.set_watching(self.team.id, created_opted_out.id, self.user.id, False)
        api.set_watching(self.team.id, subscribed.id, self.user.id, True)

        assert api.watched_saved_query_ids(self.team.id, self.user.id) == {created.id, subscribed.id}
        assert api.watched_saved_query_ids(self.team.id, member.id) == {subscribed.id, not_subscribed.id}
