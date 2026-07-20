from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.team import TeamLogsConfigSerializer
from posthog.models import OrganizationMembership, Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.logs.backend.models import (
    DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY,
    DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS,
    TeamLogsConfig,
)

# Both routes resolve to the same handler — /api/projects/ is canonical, /api/environments/
# remains as the back-compat alias. See `handle_logs_config` in posthog/api/team.py.
URL_PREFIXES = [("projects", "api/projects"), ("environments", "api/environments")]

DEFAULT_CONFIG = {
    "logs_distinct_id_attribute_key": DEFAULT_LOGS_DISTINCT_ID_ATTRIBUTE_KEY,
    "logs_session_id_attribute_keys": DEFAULT_LOGS_SESSION_ID_ATTRIBUTE_KEYS,
}


class TestTeamLogsConfig(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, prefix: str) -> str:
        return f"/{prefix}/{self.team.id}/logs_config/"

    @parameterized.expand(URL_PREFIXES)
    def test_get_returns_defaults(self, _name: str, prefix: str):
        response = self.client.get(self._url(prefix))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), DEFAULT_CONFIG)

    @parameterized.expand(URL_PREFIXES)
    def test_patch_updates_attribute_key(self, _name: str, prefix: str):
        response = self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["logs_distinct_id_attribute_key"], "user.id")

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
        self.assertEqual(response.json()["logs_distinct_id_attribute_key"], "posthog.distinct_id")

    @parameterized.expand(URL_PREFIXES)
    def test_patch_rejects_key_over_max_length(self, _name: str, prefix: str):
        response = self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "x" * 201},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(URL_PREFIXES)
    def test_regular_member_can_read_but_not_patch(self, _name: str, prefix: str):
        # Writes are admin-only, matching the admin-gated settings UI; reads stay open
        # to members so the settings page can render for everyone.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        get_response = self.client.get(self._url(prefix))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)

        patch_response = self.client.patch(
            self._url(prefix),
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)

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
        self.assertEqual(sibling_response.json(), DEFAULT_CONFIG)

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
        self.assertEqual(env_response.json()["logs_distinct_id_attribute_key"], "user.id")

    def test_patch_updates_session_id_keys_preserving_order(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/logs_config/",
            {"logs_session_id_attribute_keys": ["session.id", "posthogSessionId"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["logs_session_id_attribute_keys"], ["session.id", "posthogSessionId"])

        config = get_or_create_team_extension(self.team, TeamLogsConfig)
        self.assertEqual(config.logs_session_id_attribute_keys, ["session.id", "posthogSessionId"])

    def test_partial_patch_leaves_other_field_untouched(self):
        # A naive serializer change could make a PATCH on one field reset the other
        # to its default — the two settings must update independently.
        self.client.patch(
            f"/api/projects/{self.team.id}/logs_config/",
            {"logs_session_id_attribute_keys": ["session.id"]},
            format="json",
        )
        self.client.patch(
            f"/api/projects/{self.team.id}/logs_config/",
            {"logs_distinct_id_attribute_key": "user.id"},
            format="json",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/logs_config/")
        self.assertEqual(
            response.json(),
            {
                "logs_distinct_id_attribute_key": "user.id",
                "logs_session_id_attribute_keys": ["session.id"],
            },
        )

    def test_patch_rejects_invalid_session_id_keys(self):
        # Wiring guard: the endpoint must reject bodies the serializer marks invalid.
        # The full validation matrix lives in TestTeamLogsConfigSerializerValidation.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/logs_config/",
            {"logs_session_id_attribute_keys": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestTeamLogsConfigSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty_list", []),
            ("blank_entry", ["posthogSessionId", ""]),
            ("whitespace_entry", ["posthogSessionId", "   "]),
            ("duplicate_keys", ["session.id", "session.id"]),
            ("duplicate_after_trim", ["session.id", " session.id "]),
            ("too_many_keys", [f"key{i}" for i in range(11)]),
            ("key_over_max_length", ["x" * 201]),
        ]
    )
    def test_rejects_invalid_session_id_keys(self, _name: str, keys):
        serializer = TeamLogsConfigSerializer(data={"logs_session_id_attribute_keys": keys}, partial=True)

        self.assertFalse(serializer.is_valid())
        self.assertIn("logs_session_id_attribute_keys", serializer.errors)

    def test_trims_whitespace_from_keys(self):
        serializer = TeamLogsConfigSerializer(
            data={"logs_session_id_attribute_keys": [" session.id ", "sessionId"]}, partial=True
        )

        self.assertTrue(serializer.is_valid())
        self.assertEqual(
            serializer.validated_data["logs_session_id_attribute_keys"],
            ["session.id", "sessionId"],
        )
