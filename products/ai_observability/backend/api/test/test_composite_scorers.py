from copy import deepcopy
from typing import Any

from posthog.test.base import APIBaseTest

from django.db import connection
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

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

    def test_experiment_scope_formula_and_suite_assignment(self) -> None:
        self.payload.update(scope="experiment", apply_to_suite_keys=["agent-ci"])
        self.payload["composition"] = {
            "expression": "passed",
            "inputs": [{"alias": "passed", "statistic": "pass_rate", "scorer_version_id": str(self.version.id)}],
        }
        created = self.create_composite()
        self.assertEqual(created["scope"], "experiment")
        self.assertEqual(created["suite_keys"], ["agent-ci"])
        version = self.client.post(
            f"{self.endpoint}{created['id']}/new_version/",
            {
                "base_version": 1,
                "config": {},
                "composition": self.payload["composition"],
            },
            format="json",
        )
        self.assertEqual(version.status_code, 200, version.data)
        self.assertEqual(version.data["suite_keys"], [])
        history_url = f"{self.endpoint}{created['id']}/versions/{created['current_version_id']}/"
        self.assertEqual(self.client.get(history_url).data["suite_keys"], ["agent-ci"])
        moved = self.client.patch(
            f"{self.endpoint}{created['id']}/",
            {"suite_version_id": version.data["current_version_id"], "apply_to_suite_keys": ["agent-ci"]},
            format="json",
        )
        self.assertEqual(moved.status_code, 200, moved.data)
        self.assertEqual(moved.data["suite_keys"], ["agent-ci"])
        self.assertEqual(self.client.get(history_url).data["suite_keys"], [])
        logs = ActivityLog.objects.filter(
            team_id=self.team.id, item_id=created["id"], scope="ScoreDefinition", activity="updated"
        )
        entry = logs.get(user=self.user)
        assert entry.detail is not None
        change = next(change for change in entry.detail["changes"] if change["field"] == "suite_keys")
        self.assertEqual(change["before"], {"version_id": version.data["current_version_id"], "suite_keys": []})
        self.assertEqual(
            change["after"], {"version_id": version.data["current_version_id"], "suite_keys": ["agent-ci"]}
        )
        self.assertNotEqual(moved.data["updated_at"], version.data["updated_at"])
        retry = self.client.patch(
            f"{self.endpoint}{created['id']}/", {"apply_to_suite_keys": ["agent-ci"]}, format="json"
        )
        self.assertEqual(retry.status_code, 200, retry.data)
        self.assertEqual(retry.data["updated_at"], moved.data["updated_at"])
        self.assertEqual(logs.count(), 1)

    def test_new_version_releases_deselected_suites_and_archive_releases_all_versions(self) -> None:
        self.payload.update(scope="experiment", apply_to_suite_keys=["keep", "release"])
        self.payload["composition"] = {
            "expression": "correct",
            "inputs": [{"alias": "correct", "statistic": "pass_rate", "scorer_version_id": str(self.version.id)}],
        }
        created = self.create_composite()
        url = f"{self.endpoint}{created['id']}/"
        version = self.client.post(
            f"{url}new_version/",
            {
                "base_version": 1,
                "config": {},
                "composition": self.payload["composition"],
                "apply_to_suite_keys": ["keep"],
            },
            format="json",
        )
        self.assertEqual(version.status_code, 200, version.data)
        historical = f"{url}versions/{created['current_version_id']}/"
        self.assertEqual(self.client.get(historical).data["suite_keys"], [])
        self.payload.update(name="Second scorer", apply_to_suite_keys=["keep"])
        conflict = self.client.post(self.endpoint, self.payload, format="json")
        self.assertEqual(conflict.status_code, 400, conflict.data)
        self.assertIn("keep", str(conflict.data))
        self.assertIn(created["name"], str(conflict.data))
        self.assertEqual(self.client.get(url).data["suite_keys"], ["keep"])
        self.payload["apply_to_suite_keys"] = ["release"]
        second = self.create_composite()
        assigned = self.client.patch(
            url,
            {"suite_version_id": created["current_version_id"], "apply_to_suite_keys": ["historical"]},
            format="json",
        )
        self.assertEqual(assigned.status_code, 200, assigned.data)
        published = self.client.post(
            f"{url}new_version/",
            {
                "base_version": 2,
                "config": {},
                "composition": self.payload["composition"],
                "apply_to_suite_keys": ["keep"],
            },
            format="json",
        )
        self.assertEqual(published.status_code, 200, published.data)
        self.assertEqual(self.client.get(historical).data["suite_keys"], ["historical"])
        self.assertEqual(self.client.get(url).data["assigned_suite_keys"], ["historical", "keep"])
        archived = self.client.patch(url, {"archived": True}, format="json")
        self.assertEqual(archived.status_code, 200, archived.data)
        self.assertEqual(archived.data["suite_keys"], [])
        self.assertEqual(self.client.get(historical).data["suite_keys"], [])
        reassigned = self.client.patch(
            f"{self.endpoint}{second['id']}/", {"apply_to_suite_keys": ["historical", "keep", "release"]}, format="json"
        )
        self.assertEqual(reassigned.status_code, 200, reassigned.data)

    def test_dependency_notices_and_explicit_repinned_version(self) -> None:
        composite = self.create_composite()
        latest = self.source.create_new_version(config={"true_is_failure": True}, created_by=self.user)
        source = self.client.get(f"{self.endpoint}{self.source.id}/").data
        self.assertEqual(source["dependent_composite_count"], 1)
        dependent = self.client.get(f"{self.endpoint}{composite['id']}/").data
        self.assertEqual(dependent["input_scorers"][0]["scorer_version_id"], str(self.version.id))
        self.assertEqual(dependent["input_scorers"][0]["config"], {"true_is_failure": False})
        self.assertEqual(dependent["input_scorers"][0]["latest_version_id"], str(latest.id))
        listing = self.client.get(self.endpoint, {"input_definition_id": str(self.source.id)}).data
        self.assertEqual([item["id"] for item in listing["results"]], [composite["id"]])
        updated = deepcopy(self.payload)
        updated["composition"]["inputs"][0]["scorer_version_id"] = str(latest.id)
        updated["base_version"] = 1
        response = self.client.post(f"{self.endpoint}{composite['id']}/new_version/", updated, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["current_version"], 2)
        self.assertEqual(response.data["input_scorers"][0]["config"], {"true_is_failure": True})
        historical = self.client.get(
            f"{self.endpoint}{composite['id']}/versions/{composite['current_version_id']}/"
        ).data
        self.assertEqual(historical["composition"], self.payload["composition"])

    def test_save_query_count_does_not_grow_with_composite_inputs(self) -> None:
        inputs = []
        for index in range(16):
            source = ScoreDefinition.objects.create(team=self.team, name=f"Input {index}", kind="boolean")
            version = source.create_new_version(config={"true_is_failure": False}, created_by=self.user)
            inputs.append({"alias": f"input{index}", "scorer_version_id": str(version.id)})
        counts: dict[int, list[int]] = {}
        for input_count in (1, 16):
            payload = {
                **self.payload,
                "composition": {
                    "expression": " + ".join(f"number({item['alias']})" for item in inputs[:input_count]),
                    "inputs": inputs[:input_count],
                },
            }
            with CaptureQueriesContext(connection) as create_queries:
                response = self.client.post(self.endpoint, payload, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(len(response.data["input_scorers"]), input_count)
            with CaptureQueriesContext(connection) as version_queries:
                updated = self.client.post(
                    f"{self.endpoint}{response.data['id']}/new_version/", {**payload, "base_version": 1}, format="json"
                )
            self.assertEqual(updated.status_code, 200, updated.data)
            self.assertEqual(len(updated.data["input_scorers"]), input_count)
            counts[input_count] = [len(create_queries), len(version_queries)]
        self.assertLessEqual(counts[16][0], counts[1][0])
        self.assertLessEqual(counts[16][1], counts[1][1])

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

    @parameterized.expand(
        [
            (
                "unknown_category",
                "categorical",
                {"options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}]},
                '"graet" if correct else "bad"',
            ),
            (
                "selection_count",
                "categorical",
                {
                    "options": [{"key": "good", "label": "Good"}, {"key": "bad", "label": "Bad"}],
                    "selection_mode": "multiple",
                    "min_selections": 2,
                },
                '"good" if correct else "bad"',
            ),
            ("increment", "numeric", {"step": 0.5}, "number(correct)"),
            ("parser_limit", "numeric", {}, "(x," * 199),
        ]
    )
    def test_invalid_output_and_parser_limits_are_rejected_on_all_write_paths(
        self, _name: str, kind: str, config: dict[str, Any], expression: str
    ) -> None:
        self.payload["kind"] = kind
        self.payload["config"] = {"options": [{"key": "good", "label": "Good"}]} if kind == "categorical" else {}
        self.payload["composition"]["expression"] = (
            '"good" if correct else "good"' if kind == "categorical" else "number(correct)"
        )
        composite = self.create_composite()
        self.payload["config"] = config
        self.payload["composition"]["expression"] = expression
        for endpoint in (
            self.endpoint,
            f"{self.endpoint}validate_composition/",
            f"{self.endpoint}{composite['id']}/new_version/",
        ):
            response = self.client.post(endpoint, self.payload, format="json")
            self.assertEqual(response.status_code, 400, response.data)

    def test_historical_version_access_is_checked_independently_of_current_version(self) -> None:
        composite = self.create_composite()
        visible_source = ScoreDefinition.objects.create(team=self.team, name="Visible input", kind="boolean")
        visible_version = visible_source.create_new_version(config={}, created_by=self.user)
        current = ScoreDefinition.objects.get(id=composite["id"]).create_new_version(
            config={},
            composition={
                "expression": "number(visible)",
                "inputs": [{"alias": "visible", "scorer_version_id": str(visible_version.id)}],
            },
            created_by=self.user,
        )
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "history-viewer@example.com", "test-password")
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
        detail = f"{self.endpoint}{composite['id']}/"
        self.assertEqual(self.client.get(detail).status_code, 200)
        versions = self.client.get(f"{detail}versions/")
        self.assertEqual(versions.status_code, 200, versions.data)
        self.assertEqual([row["id"] for row in versions.data["results"]], [str(current.id)])
        self.assertEqual(versions.data["count"], 1)
        self.assertEqual(self.client.get(f"{detail}versions/{current.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"{detail}versions/{composite['current_version_id']}/").status_code, 404)

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

    @parameterized.expand([("allowed", False), ("denied", True)])
    def test_input_access_controls_composite_visibility_and_creation(self, _name: str, deny_input: bool) -> None:
        composite = self.create_composite()
        experiment = self.client.post(
            self.endpoint,
            {
                **self.payload,
                "name": "Experiment mean",
                "scope": "experiment",
                "composition": {
                    "expression": "mean",
                    "inputs": [
                        {"alias": "mean", "scorer_version_id": composite["current_version_id"], "statistic": "mean"}
                    ],
                },
            },
            format="json",
        )
        self.assertEqual(experiment.status_code, 201, experiment.data)
        experiment_url = f"{self.endpoint}{experiment.data['id']}/"
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "composite-viewer@example.com", "test-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="member"
        )
        if deny_input:
            AccessControl.objects.create(
                team=self.team,
                resource="llm_analytics",
                resource_id=str(self.source.id),
                organization_member=membership,
                access_level="none",
            )
        self.client.force_login(member)
        for suffix in ("", "versions/", f"versions/{composite['current_version_id']}/"):
            self.assertEqual(
                self.client.get(f"{self.endpoint}{composite['id']}/{suffix}").status_code, 404 if deny_input else 200
            )
        visible_ids = {item["id"] for item in self.client.get(self.endpoint).data["results"]}
        self.assertEqual(
            visible_ids, set() if deny_input else {str(self.source.id), composite["id"], experiment.data["id"]}
        )
        self.assertEqual(self.client.get(experiment_url).status_code, 404 if deny_input else 200)
        self.assertEqual(
            self.client.get(f"{experiment_url}versions/{experiment.data['current_version_id']}/").status_code,
            404 if deny_input else 200,
        )
        edit = self.client.patch(f"{self.endpoint}{composite['id']}/", {"description": "Overall score"}, format="json")
        self.assertEqual(edit.status_code, 404 if deny_input else 200, edit.data)
        self.assertEqual(
            self.client.post(self.endpoint, self.payload, format="json").status_code, 400 if deny_input else 201
        )
        self.assertEqual(
            self.client.post(f"{self.endpoint}validate_composition/", self.payload, format="json").status_code,
            400 if deny_input else 200,
        )
