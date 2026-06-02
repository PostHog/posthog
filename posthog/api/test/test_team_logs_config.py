from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership, Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.logs.backend.models import TeamLogsConfig

# Both routes resolve to the same handler — /api/projects/ is canonical, /api/environments/
# remains as the back-compat alias. See `handle_logs_config` in posthog/api/team.py.
URL_PREFIXES = [("projects", "api/projects"), ("environments", "api/environments")]


class TestTeamLogsConfig(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, prefix: str) -> str:
        return f"/{prefix}/{self.team.id}/logs_config/"

    @parameterized.expand(URL_PREFIXES)
    def test_get_returns_default_attribute_key(self, _name: str, prefix: str):
        response = self.client.get(self._url(prefix))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "posthogDistinctId"})

    @parameterized.expand(URL_PREFIXES)
    def test_patch_updates_attribute_key(self, _name: str, prefix: str):
        response = self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "user.id"})

        config = get_or_create_team_extension(self.team, TeamLogsConfig)
        self.assertEqual(config.logs_distinct_id_attribute_key, "user.id")

    @parameterized.expand(URL_PREFIXES)
    def test_patch_persists_across_requests(self, _name: str, prefix: str):
        self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "posthog.distinct_id"},
            format="json",
        )

        response = self.client.get(self._url(prefix))
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "posthog.distinct_id"})

    @parameterized.expand(URL_PREFIXES)
    def test_patch_rejects_key_over_max_length(self, _name: str, prefix: str):
        response = self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "x" * 201},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(URL_PREFIXES)
    def test_regular_member_can_patch(self, _name: str, prefix: str):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"logs_distinct_id_attribute_key": "user.id"})

    @parameterized.expand(URL_PREFIXES)
    def test_config_is_scoped_per_environment(self, _name: str, prefix: str):
        # Each environment under a project must keep its own config. A write on this
        # environment must not leak to a sibling environment that shares its project.
        sibling = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="sibling-env",
        )

        self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )

        sibling_response = self.client.get(f"/{prefix}/{sibling.id}/logs_config/")
        self.assertEqual(
            sibling_response.json(),
            {"logs_distinct_id_attribute_key": "posthogDistinctId"},
        )

    def test_project_and_environment_share_same_config(self):
        # Writes via the canonical /api/projects/ URL must be visible via the
        # /api/environments/ alias and vice versa — both routes operate on the
        # same env-scoped TeamLogsConfig keyed by team_id.
        self.client.patch(
            f"/api/projects/{self.team.id}/logs_config/",
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )
        env_response = self.client.get(f"/api/environments/{self.team.id}/logs_config/")
        self.assertEqual(env_response.json(), {"logs_distinct_id_attribute_key": "user.id"})
