from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.team import TeamTracingConfigSerializer
from posthog.models import OrganizationMembership, Team
from posthog.models.team.extensions import get_or_create_team_extension

from products.tracing.backend.facade.team_extension import (
    DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEYS,
    DEFAULT_TRACING_SESSION_ID_ATTRIBUTE_KEYS,
    TeamTracingConfig,
)

# Both routes resolve to the same handler — /api/projects/ is canonical, /api/environments/
# remains as the back-compat alias. See `handle_tracing_config` in posthog/api/team.py.
URL_PREFIXES = [("projects", "api/projects"), ("environments", "api/environments")]

DEFAULT_CONFIG = {
    "tracing_distinct_id_attribute_keys": DEFAULT_TRACING_DISTINCT_ID_ATTRIBUTE_KEYS,
    "tracing_session_id_attribute_keys": DEFAULT_TRACING_SESSION_ID_ATTRIBUTE_KEYS,
}


class TestTeamTracingConfig(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _url(self, prefix: str) -> str:
        return f"/{prefix}/{self.team.id}/tracing_config/"

    @parameterized.expand(URL_PREFIXES)
    def test_get_returns_defaults(self, _name: str, prefix: str):
        response = self.client.get(self._url(prefix))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), DEFAULT_CONFIG)

    @parameterized.expand(URL_PREFIXES)
    def test_patch_updates_distinct_id_keys(self, _name: str, prefix: str):
        response = self.client.patch(
            self._url(prefix),
            {"tracing_distinct_id_attribute_keys": ["user.id", "posthogDistinctId"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tracing_distinct_id_attribute_keys"], ["user.id", "posthogDistinctId"])

        config = get_or_create_team_extension(self.team, TeamTracingConfig)
        self.assertEqual(config.tracing_distinct_id_attribute_keys, ["user.id", "posthogDistinctId"])

    @parameterized.expand(URL_PREFIXES)
    def test_patch_persists_across_requests(self, _name: str, prefix: str):
        self.client.patch(
            self._url(prefix),
            {"tracing_distinct_id_attribute_keys": ["posthog.distinct_id"]},
            format="json",
        )

        response = self.client.get(self._url(prefix))
        self.assertEqual(response.json()["tracing_distinct_id_attribute_keys"], ["posthog.distinct_id"])

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
            {"tracing_distinct_id_attribute_keys": ["user.id"]},
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
            {"tracing_distinct_id_attribute_keys": ["user.id"]},
            format="json",
        )

        sibling_response = self.client.get(f"/{prefix}/{sibling.id}/tracing_config/")
        self.assertEqual(sibling_response.json(), DEFAULT_CONFIG)

    def test_project_and_environment_share_same_config(self):
        # Writes via the canonical /api/projects/ URL must be visible via the
        # /api/environments/ alias and vice versa — both routes operate on the
        # same env-scoped TeamTracingConfig keyed by team_id.
        self.client.patch(
            f"/api/projects/{self.team.id}/tracing_config/",
            {"tracing_distinct_id_attribute_keys": ["user.id"]},
            format="json",
        )
        env_response = self.client.get(f"/api/environments/{self.team.id}/tracing_config/")
        self.assertEqual(env_response.json()["tracing_distinct_id_attribute_keys"], ["user.id"])

    def test_patch_updates_session_id_keys_preserving_order(self):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/tracing_config/",
            {"tracing_session_id_attribute_keys": ["session.id", "posthogSessionId"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tracing_session_id_attribute_keys"], ["session.id", "posthogSessionId"])

        config = get_or_create_team_extension(self.team, TeamTracingConfig)
        self.assertEqual(config.tracing_session_id_attribute_keys, ["session.id", "posthogSessionId"])

    def test_partial_patch_leaves_other_field_untouched(self):
        # A naive serializer change could make a PATCH on one field reset the other
        # to its default — the two settings must update independently.
        self.client.patch(
            f"/api/projects/{self.team.id}/tracing_config/",
            {"tracing_session_id_attribute_keys": ["session.id"]},
            format="json",
        )
        self.client.patch(
            f"/api/projects/{self.team.id}/tracing_config/",
            {"tracing_distinct_id_attribute_keys": ["user.id"]},
            format="json",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/tracing_config/")
        self.assertEqual(
            response.json(),
            {
                "tracing_distinct_id_attribute_keys": ["user.id"],
                "tracing_session_id_attribute_keys": ["session.id"],
            },
        )

    @parameterized.expand(
        [
            ("distinct_id", "tracing_distinct_id_attribute_keys"),
            ("session_id", "tracing_session_id_attribute_keys"),
        ]
    )
    def test_patch_rejects_invalid_keys(self, _name: str, field: str):
        # Wiring guard: the endpoint must reject bodies the serializer marks invalid.
        # The full validation matrix lives in TestTeamTracingConfigSerializerValidation.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/tracing_config/",
            {field: []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


KEY_LIST_FIELDS = ["tracing_distinct_id_attribute_keys", "tracing_session_id_attribute_keys"]

INVALID_KEY_LISTS = [
    ("empty_list", []),
    ("blank_entry", ["sessionId", ""]),
    ("whitespace_entry", ["sessionId", "   "]),
    ("duplicate_keys", ["session.id", "session.id"]),
    ("duplicate_after_trim", ["session.id", " session.id "]),
    ("too_many_keys", [f"key{i}" for i in range(11)]),
    ("key_over_max_length", ["x" * 201]),
]


class TestTeamTracingConfigSerializerValidation(SimpleTestCase):
    @parameterized.expand(
        [(f"{field}_{name}", field, keys) for field in KEY_LIST_FIELDS for name, keys in INVALID_KEY_LISTS]
    )
    def test_rejects_invalid_keys(self, _name: str, field: str, keys):
        serializer = TeamTracingConfigSerializer(data={field: keys}, partial=True)

        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    @parameterized.expand([(field,) for field in KEY_LIST_FIELDS])
    def test_trims_whitespace_from_keys(self, field: str):
        serializer = TeamTracingConfigSerializer(data={field: [" first.key ", "second.key"]}, partial=True)

        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data[field], ["first.key", "second.key"])
