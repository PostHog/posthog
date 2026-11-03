from collections.abc import Callable
from typing import Any

from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from rest_framework.serializers import Serializer
from rest_framework.test import APIRequestFactory

from posthog.api.project import ProjectBackwardCompatSerializer
from posthog.api.team.team_serializer import TeamSerializer
from posthog.models import User
from posthog.models.organization import OrganizationMembership
from posthog.models.project import Project
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.team.team_revenue_analytics_config import TeamRevenueAnalyticsConfig
from posthog.user_permissions import UserPermissions

SERIALIZERS = [("team", TeamSerializer), ("project", ProjectBackwardCompatSerializer)]


def _set_timezone(team: Team) -> None:
    team = Team.objects.get(pk=team.pk)
    team.timezone = "Europe/Lisbon"
    team.save()


def _filter_revenue_test_accounts(team: Team) -> None:
    config = get_or_create_team_extension(team, TeamRevenueAnalyticsConfig)
    config.filter_test_accounts = True
    config.save()


class TestTeamSharedRepresentation(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        Team.objects.filter(pk=self.team.pk).update(ingested_event=True)
        self.team.refresh_from_db()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.member = User.objects.create_and_join(
            self.organization, "member@example.com", "password", level=OrganizationMembership.Level.MEMBER
        )

    def _render(self, serializer_class: type[Serializer], user: User) -> tuple[dict[str, Any], list[str]]:
        request = APIRequestFactory().get("/")
        request.user = user
        team = Team.objects.get(pk=self.team.pk)
        instance = team if serializer_class is TeamSerializer else Project.objects.get(pk=team.project_id)
        context = {"request": request, "user_permissions": UserPermissions(user=user, team=team)}
        with self.captureOnCommitCallbacks(execute=True), CaptureQueriesContext(connection) as queries:
            data = serializer_class(instance, context=context).data
        return data, [query["sql"] for query in queries.captured_queries]

    @parameterized.expand(SERIALIZERS)
    def test_each_caller_gets_their_own_fields_from_one_shared_entry(
        self, _name: str, serializer_class: type[Serializer]
    ) -> None:
        # The first render creates the team's missing extension rows, and each new row bumps the version.
        self._render(serializer_class, self.user)
        admin_data, _ = self._render(serializer_class, self.user)
        member_data, member_queries = self._render(serializer_class, self.member)

        self.assertEqual(admin_data["effective_membership_level"], OrganizationMembership.Level.ADMIN)
        self.assertEqual(member_data["effective_membership_level"], OrganizationMembership.Level.MEMBER)
        self.assertEqual(member_data["name"], admin_data["name"])
        self.assertEqual(member_data["revenue_analytics_config"], admin_data["revenue_analytics_config"])
        self.assertFalse([sql for sql in member_queries if "posthog_teamrevenueanalyticsconfig" in sql])

    @parameterized.expand(
        [
            (f"{name}_{write_name}", serializer_class, write, read, expected)
            for name, serializer_class in SERIALIZERS
            for write_name, write, read, expected in [
                ("team_row", _set_timezone, lambda data: data["timezone"], "Europe/Lisbon"),
                (
                    "extension",
                    _filter_revenue_test_accounts,
                    lambda data: data["revenue_analytics_config"]["filter_test_accounts"],
                    True,
                ),
            ]
        ]
    )
    def test_a_write_shows_on_the_next_read(
        self,
        _name: str,
        serializer_class: type[Serializer],
        write: Callable[[Team], None],
        read: Callable[[dict[str, Any]], object],
        expected: object,
    ) -> None:
        self._render(serializer_class, self.user)

        write(self.team)
        data, _ = self._render(serializer_class, self.user)

        self.assertEqual(read(data), expected)

    @parameterized.expand(SERIALIZERS)
    def test_a_project_without_an_event_is_not_cached(self, _name: str, serializer_class: type[Serializer]) -> None:
        Team.objects.filter(pk=self.team.pk).update(ingested_event=False)
        self._render(serializer_class, self.user)

        # Ingestion sets the flag with raw SQL, which sends no signal.
        Team.objects.filter(pk=self.team.pk).update(ingested_event=True)
        data, _ = self._render(serializer_class, self.user)

        self.assertTrue(data["ingested_event"])
