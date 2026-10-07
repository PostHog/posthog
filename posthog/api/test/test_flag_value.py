from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def targeted_rule(rule_id: str, value: Any) -> dict[str, Any]:
    return {
        "id": rule_id,
        "rule_type": "targeted_release",
        "targeting": {"properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "beta"}]},
        "value": value,
    }


def rollout_rule(rule_id: str, value: Any) -> dict[str, Any]:
    return {
        "id": rule_id,
        "rule_type": "percentage_rollout",
        "targeting": {"properties": []},
        "value": value,
        "rollout_percentage": 50,
        "on_rollout_miss": "continue",
        "assignment_algorithm": "sha1_60_v1",
        "seed": "values-endpoint-seed",
    }


def split_rule(rule_id: str, *values: Any) -> dict[str, Any]:
    return {
        "id": rule_id,
        "rule_type": "experiment",
        "targeting": {"properties": []},
        "experiment_id": None,
        "paused": False,
        "rollout_percentage": 100,
        "on_rollout_miss": "continue",
        "assignment_algorithm": "sha1_60_v1",
        "seed": "values-endpoint-split",
        "variants": [{"key": f"arm_{index}", "weight": 50, "value": value} for index, value in enumerate(values)],
    }


def v2_document(return_type: str, default_value: Any, *rules: dict[str, Any]) -> dict[str, Any]:
    return {"version": 2, "return_type": return_type, "default_value": default_value, "rules": list(rules)}


RULE_A = "0b6f5a3c-1d2e-4f70-8a9b-0c1d2e3f4a5b"
RULE_B = "1c7a6b4d-2e3f-4a81-9bac-1d2e3f4a5b6c"
RULE_C = "2d8b7c5e-3f4a-4b92-8cbd-2e3f4a5b6c7d"


class TestFlagValueViewSet(APIBaseTest):
    def _values(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        flag = FeatureFlag.objects.create(team=self.team, key="values-flag", created_by=self.user, filters=filters)
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()["results"]

    @parameterized.expand(
        [
            (
                "rule_order_then_default",
                v2_document(
                    "string",
                    "standard",
                    targeted_rule(RULE_A, "compact"),
                    rollout_rule(RULE_B, "wide"),
                    targeted_rule(RULE_C, "compact"),
                ),
                ["compact", "wide", "standard"],
            ),
            (
                "null_default",
                v2_document("string", None, rollout_rule(RULE_A, "wide"), targeted_rule(RULE_B, "compact")),
                ["wide", "compact"],
            ),
            (
                "default_repeats_a_rule_value",
                v2_document("string", "compact", targeted_rule(RULE_A, "compact")),
                ["compact"],
            ),
            ("no_rules", v2_document("string", "standard"), ["standard"]),
            (
                "variant_values_in_stored_order",
                v2_document("string", "standard", targeted_rule(RULE_A, "wide"), split_rule(RULE_B, "compact", "wide")),
                ["wide", "compact", "standard"],
            ),
        ]
    )
    def test_flag_values_v2_string_flag_lists_its_strings(
        self, _name: str, filters: dict[str, Any], strings: list[str]
    ) -> None:
        expected = [{"name": True}, {"name": False}, *({"name": value} for value in strings)]
        self.assertEqual(self._values(filters), expected)

    @parameterized.expand(
        [
            ("boolean", v2_document("boolean", False, targeted_rule(RULE_A, True), rollout_rule(RULE_B, True))),
            ("number", v2_document("number", 3, targeted_rule(RULE_A, 10), rollout_rule(RULE_B, 0))),
            ("object", v2_document("object", None, targeted_rule(RULE_A, {"layout": "grid"}))),
        ]
    )
    def test_flag_values_v2_non_string_flag_lists_true_and_false(self, _name: str, filters: dict[str, Any]) -> None:
        self.assertEqual(self._values(filters), [{"name": True}, {"name": False}])

    @parameterized.expand(
        [
            ("v2_without_rules_key", {"version": 2, "return_type": "string", "default_value": "standard"}),
            ("v2_rules_not_a_list", {"version": 2, "return_type": "string", "default_value": None, "rules": "x"}),
            (
                "unsupported_version",
                {"version": 3, "multivariate": {"variants": [{"key": "variant1", "rollout_percentage": 100}]}},
            ),
        ]
    )
    def test_flag_values_unreadable_config_lists_true_and_false(self, _name: str, filters: dict[str, Any]) -> None:
        self.assertEqual(self._values(filters), [{"name": True}, {"name": False}])

    def test_flag_values_boolean_flag(self):
        """Test that boolean flags return true/false values."""
        flag = FeatureFlag.objects.create(
            name="Boolean Flag",
            key="boolean-flag",
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [{"name": True}, {"name": False}]
        self.assertEqual(data["results"], expected_values)

    def test_flag_values_multivariate_flag(self):
        """Test that multivariate flags return true/false plus variant keys."""
        flag = FeatureFlag.objects.create(
            name="Multivariate Flag",
            key="multivariate-flag",
            team=self.team,
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "variant1", "rollout_percentage": 50},
                        {"key": "variant2", "rollout_percentage": 50},
                    ]
                },
            },
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [
            {"name": True},
            {"name": False},
            {"name": "variant1"},
            {"name": "variant2"},
        ]
        self.assertEqual(data["results"], expected_values)

    def test_flag_values_missing_key_parameter(self):
        """Test that missing key parameter returns 400."""
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()
        self.assertEqual(data["error"], "Missing flag ID parameter")

    def test_flag_values_invalid_key_parameter(self):
        """Test that invalid key parameter returns 400."""
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key=invalid")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()
        self.assertEqual(data["error"], "Invalid flag ID - must be a valid integer")

    def test_flag_values_nonexistent_flag(self):
        """Test that nonexistent flag returns 404."""
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key=99999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        data = response.json()
        self.assertEqual(data["error"], "Feature flag not found")

    def test_flag_values_flag_from_different_team(self):
        """Test that flag from different team returns 404."""
        # Create a different team and flag

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        other_flag = FeatureFlag.objects.create(
            name="Other Flag",
            key="other-flag",
            team=other_team,
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={other_flag.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        data = response.json()
        self.assertEqual(data["error"], "Feature flag not found")

    def test_flag_values_deleted_flag(self):
        """Test that deleted flag returns 404."""
        flag = FeatureFlag.objects.create(
            name="Deleted Flag",
            key="deleted-flag",
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
            deleted=True,
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        data = response.json()
        self.assertEqual(data["error"], "Feature flag not found")

    def test_flag_values_multivariate_no_variants(self):
        """Test multivariate flag with no variants returns only true/false."""
        flag = FeatureFlag.objects.create(
            name="Multivariate No Variants",
            key="multivariate-no-variants",
            team=self.team,
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {},
            },
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [{"name": True}, {"name": False}]
        self.assertEqual(data["results"], expected_values)

    def test_flag_values_multivariate_with_empty_variant_key(self):
        """Test multivariate flag with empty variant key ignores that variant."""
        flag = FeatureFlag.objects.create(
            name="Multivariate Empty Key",
            key="multivariate-empty-key",
            team=self.team,
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "valid_variant", "rollout_percentage": 50},
                        {"key": "", "rollout_percentage": 25},  # Empty key should be ignored
                        {"rollout_percentage": 25},  # No key should be ignored
                    ]
                },
            },
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [
            {"name": True},
            {"name": False},
            {"name": "valid_variant"},
        ]
        self.assertEqual(data["results"], expected_values)

    def test_flag_values_respects_object_level_access_control(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        other_user = self._create_user("other_user@posthog.com")

        flag = FeatureFlag.objects.create(
            name="Hidden Flag",
            key="hidden-flag",
            team=self.team,
            created_by=self.user,
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {"variants": [{"key": "secret-variant", "rollout_percentage": 100}]},
            },
        )
        AccessControl.objects.create(resource="feature_flag", resource_id=flag.id, team=self.team, access_level="none")

        self.client.force_login(other_user)
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("feature_flag_read", ["feature_flag:read"], status.HTTP_200_OK),
            ("feature_flag_write", ["feature_flag:write"], status.HTTP_200_OK),
            ("unrelated_scope", ["dashboard:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_flag_values_scoped_personal_api_key(self, _name, scopes, expected_status):
        flag = FeatureFlag.objects.create(
            name="Scoped Flag",
            key="scoped-flag",
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="scoped", user=self.user, scopes=scopes, secure_value=hash_key_value(token))
        self.client.logout()

        response = self.client.get(
            f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}",
            headers={"authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, expected_status, response.content)
