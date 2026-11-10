from copy import deepcopy
from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.models.score_definitions import ScoreDefinition


class TestCompositeScorers(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.endpoint = f"/api/environments/{self.team.id}/llm_analytics/score_definitions/"
        self.source = ScoreDefinition.objects.create(team=self.team, name="Correct", kind="boolean")
        self.version = self.source.create_new_version(config={"true_is_failure": False}, created_by=self.user)
        self.payload: dict[str, Any] = {
            "name": "Overall",
            "kind": "numeric",
            "calculation": "composite",
            "config": {"min": 0, "max": 1},
            "composition": {
                "expression": "number(correct)",
                "inputs": [{"alias": "correct", "scorer_version_id": str(self.version.id)}],
            },
        }

    def create_composite(self) -> dict[str, Any]:
        response = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_dependency_notices_and_explicit_repinned_version(self) -> None:
        composite = self.create_composite()
        latest = self.source.create_new_version(config={"true_is_failure": True}, created_by=self.user)
        source = self.client.get(f"{self.endpoint}{self.source.id}/").data
        self.assertEqual(source["dependent_composite_count"], 1)
        dependent = self.client.get(f"{self.endpoint}{composite['id']}/").data
        self.assertEqual(dependent["input_scorers"][0]["scorer_version_id"], str(self.version.id))
        self.assertEqual(dependent["input_scorers"][0]["latest_version_id"], str(latest.id))
        listing = self.client.get(self.endpoint, {"input_definition_id": str(self.source.id)}).data
        self.assertEqual([item["id"] for item in listing["results"]], [composite["id"]])
        updated = deepcopy(self.payload)
        updated["composition"]["inputs"][0]["scorer_version_id"] = str(latest.id)
        updated["base_version"] = 1
        response = self.client.post(f"{self.endpoint}{composite['id']}/new_version/", updated, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["current_version"], 2)
        historical = self.client.get(
            f"{self.endpoint}{composite['id']}/versions/{composite['current_version_id']}/"
        ).data
        self.assertEqual(historical["composition"], self.payload["composition"])

    @parameterized.expand(
        [("numeric", "number(correct)"), ("boolean", "not correct"), ("categorical", '"good" if correct else "bad"')]
    )
    def test_boolean_input_supports_every_output_kind(self, kind: str, expression: str) -> None:
        self.payload["kind"] = kind
        self.payload["config"] = (
            {"options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}]}
            if kind == "categorical"
            else {}
        )
        self.payload["composition"]["expression"] = expression
        self.create_composite()

    def test_categorical_input_can_produce_numeric_score(self) -> None:
        source = ScoreDefinition.objects.create(team=self.team, name="Relevance", kind="categorical")
        version = source.create_new_version(
            config={"options": [{"key": "good", "label": "Good"}]}, created_by=self.user
        )
        self.payload["composition"]["inputs"][0]["scorer_version_id"] = str(version.id)
        self.payload["composition"]["expression"] = 'number("good" in correct)'
        self.create_composite()

    def test_rejects_nested_and_foreign_inputs(self) -> None:
        composite = self.create_composite()
        foreign = ScoreDefinition.objects.create(
            team=Team.objects.create(organization=self.organization), name="Foreign", kind="boolean"
        )
        foreign_version = foreign.create_new_version(config={}, created_by=self.user)
        for version_id in (composite["current_version_id"], str(foreign_version.id)):
            self.payload["composition"]["inputs"][0]["scorer_version_id"] = version_id
            response = self.client.post(self.endpoint, self.payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)
            validation = self.client.post(f"{self.endpoint}validate_composition/", self.payload, format="json")
            self.assertEqual(validation.status_code, 400, validation.data)

    @parameterized.expand(
        [
            ("read", ["llm_analytics:read"], 200),
            ("ingestion_only", ["offline_evaluation_ingestion:write"], 403),
        ]
    )
    def test_validate_without_saving_requires_read_scope(self, _name: str, scopes: list[str], expected: int) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        before = ScoreDefinition.objects.filter(team=self.team).count()
        response = self.client.post(f"{self.endpoint}validate_composition/", self.payload, format="json")
        self.assertEqual(response.status_code, expected, response.data)
        self.assertEqual(ScoreDefinition.objects.filter(team=self.team).count(), before)
        if expected == 200:
            self.assertEqual(response.data, {"valid": True})
            self.payload["composition"]["expression"] = "unknown_input + 1"
            invalid = self.client.post(f"{self.endpoint}validate_composition/", self.payload, format="json")
            self.assertEqual(invalid.status_code, 400, invalid.data)

    def test_denied_input_hides_composite_and_prevents_new_definition(self) -> None:
        composite = self.create_composite()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "composite-viewer@example.com", "test-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="member"
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=str(self.source.id),
            organization_member=membership,
            access_level="none",
        )
        self.client.force_login(member)
        for suffix in ("", "versions/", f"versions/{composite['current_version_id']}/"):
            self.assertEqual(self.client.get(f"{self.endpoint}{composite['id']}/{suffix}").status_code, 404)
        self.assertEqual(self.client.get(self.endpoint).data["results"], [])
        self.assertEqual(self.client.post(self.endpoint, self.payload, format="json").status_code, 400)
        self.assertEqual(
            self.client.post(f"{self.endpoint}validate_composition/", self.payload, format="json").status_code, 400
        )
