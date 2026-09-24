from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from drf_spectacular.generators import SchemaGenerator
from parameterized import parameterized
from rest_framework import status
from rest_framework.routers import SimpleRouter

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Project, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.api.offline_experiments import OfflineExperimentViewSet
from products.ai_observability.backend.models.datasets import Dataset, DatasetItem, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineExperiment,
    OfflineExperimentItem,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition


@pytest.mark.ee
class TestOfflineExperimentsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.feature_flag = self.enterContext(
            patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        )
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

    def _endpoint(self, experiment_id: str = "", action: str = "", team_id: int | None = None) -> str:
        base = f"/api/projects/{team_id or self.team.id}/ai_observability/offline_experiments/"
        return f"{base}{experiment_id}/{action}/" if experiment_id else base

    def _authenticate(self, auth_kind: str, scopes: list[str] | None = None, user: User | None = None) -> None:
        self.client.logout()
        self.client.credentials()
        user = user or self.user
        scopes = scopes if scopes is not None else ["offline_evaluation_ingestion:write"]
        if auth_kind == "session":
            self.client.force_login(user)
            return
        if auth_kind == "personal_key":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=user,
                label="Offline evaluation test",
                secure_value=hash_key_value(token),
                scopes=scopes,
                scoped_teams=[self.team.id],
            )
        elif auth_kind == "project_key":
            token = f"phs_{uuid4().hex}"
            ProjectSecretAPIKey.objects.create(
                team=self.team,
                label="Offline evaluation test",
                secure_value=hash_key_value(token),
                scopes=scopes,
            )
        else:
            raise ValueError(auth_kind)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _experiment_body(self) -> dict[str, object]:
        return {"id": str(uuid4()), "name": "Answer quality", "started_at": timezone.now().isoformat()}

    def _evaluation_member(self, access_level: str = "editor") -> OrganizationMembership:
        member = User.objects.create_and_join(self.organization, "eval-member@example.com", "test-password")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
            organization_member=None,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="evaluation",
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )
        return membership

    def _dataset_item_version(self) -> DatasetItemVersion:
        dataset = Dataset.objects.for_team(self.team.id).create(team=self.team, name="Questions")
        revision = DatasetRevision.objects.for_team(self.team.id).create(team=self.team, dataset=dataset, revision=1)
        item = DatasetItem.objects.for_team(self.team.id).create(team=self.team, dataset=dataset)
        return DatasetItemVersion.objects.for_team(self.team.id).create(
            team=self.team,
            dataset=dataset,
            dataset_item=item,
            dataset_revision=revision,
            version=1,
            input="What is 2 + 2?",
        )

    @parameterized.expand([("session",), ("personal_key",), ("project_key",)])
    def test_ingestion_and_both_lifecycle_actions(self, auth_kind: str) -> None:
        definition = ScoreDefinition.objects.create(team=self.team, name="Correct", kind="boolean")
        version = definition.create_new_version(config={"true_label": "Yes", "false_label": "No"}, created_by=self.user)
        self._authenticate(auth_kind)
        body = self._experiment_body() | {"expected_item_count": 1, "expected_result_count": 1}
        created = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        experiment_id = str(body["id"])
        self.assertEqual(created.data["id"], experiment_id)

        incomplete = self.client.post(self._endpoint(experiment_id, "complete"), {}, format="json")
        self.assertEqual(incomplete.status_code, status.HTTP_409_CONFLICT, incomplete.data)
        self.assertEqual(incomplete.data["code"], "expected_count_mismatch")
        self.assertEqual(incomplete.data["expected_item_count"], 1)
        self.assertEqual(incomplete.data["expected_result_count"], 1)
        self.assertEqual(incomplete.data["accepted_item_count"], 0)
        self.assertEqual(incomplete.data["accepted_result_count"], 0)

        item_id = str(uuid4())
        uploaded = self.client.post(
            self._endpoint(experiment_id, "upload"),
            {
                "items": [{"id": item_id, "payload": {"input": "What is 2 + 2?", "output": "5"}}],
                "results": [{"item_id": item_id, "scorer_version_id": str(version.id), "status": "ok", "value": False}],
            },
            format="json",
        )
        self.assertEqual(uploaded.status_code, status.HTTP_200_OK, uploaded.data)
        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(pk=uploaded.data["results"][0]["id"])
        self.assertIs(result.boolean_value, False)
        self.assertEqual(result.scorer_version_id, version.id)

        completed = self.client.post(self._endpoint(experiment_id, "complete"), {}, format="json")
        self.assertEqual(completed.status_code, status.HTTP_200_OK, completed.data)
        self.assertEqual(completed.data["status"], "completed")
        self.assertEqual(completed.data["accepted_item_count"], 1)
        self.assertEqual(completed.data["accepted_result_count"], 1)

        failed_body = self._experiment_body() | {"expected_result_count": 10}
        self.assertEqual(
            self.client.post(self._endpoint(), failed_body, format="json").status_code, status.HTTP_201_CREATED
        )
        failed = self.client.post(self._endpoint(str(failed_body["id"]), "fail"), {}, format="json")
        self.assertEqual(failed.status_code, status.HTTP_200_OK, failed.data)
        self.assertEqual(failed.data["status"], "failed")
        self.assertEqual(failed.data["accepted_result_count"], 0)

    @parameterized.expand(
        [
            ("personal_missing", "personal_key", []),
            ("personal_read", "personal_key", ["offline_evaluation_ingestion:read"]),
            ("personal_evaluation_write", "personal_key", ["evaluation:write"]),
            ("project_missing", "project_key", []),
            ("project_read", "project_key", ["offline_evaluation_ingestion:read"]),
            ("project_evaluation_write", "project_key", ["evaluation:write"]),
        ]
    )
    def test_ingestion_requires_its_own_write_scope(self, _name: str, auth_kind: str, scopes: list[str]) -> None:
        self._authenticate(auth_kind, scopes=scopes)
        response = self.client.post(self._endpoint(), self._experiment_body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(OfflineExperiment.objects.for_team(self.team.id).exists())

    @parameterized.expand([("personal_key",), ("project_key",)])
    def test_project_scoped_key_cannot_write_to_another_project(self, auth_kind: str) -> None:
        _, other_team = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)
        self._authenticate(auth_kind)
        response = self.client.post(self._endpoint(team_id=other_team.id), self._experiment_body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(OfflineExperiment.objects.for_team(other_team.id).exists())

    @parameterized.expand([("session",), ("personal_key",), ("project_key",)])
    def test_rollout_flag_is_required_for_every_authentication_method(self, auth_kind: str) -> None:
        self._authenticate(auth_kind)
        self.feature_flag.return_value = False
        response = self.client.post(self._endpoint(), self._experiment_body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(OfflineExperiment.objects.for_team(self.team.id).exists())

    @parameterized.expand(
        [
            ("session_viewer", "session", "viewer", status.HTTP_403_FORBIDDEN),
            ("session_editor", "session", "editor", status.HTTP_201_CREATED),
            ("personal_key_viewer", "personal_key", "viewer", status.HTTP_403_FORBIDDEN),
            ("personal_key_editor", "personal_key", "editor", status.HTTP_201_CREATED),
            ("project_key", "project_key", "none", status.HTTP_201_CREATED),
        ]
    )
    def test_human_callers_require_evaluation_editor_access(
        self, _name: str, auth_kind: str, access_level: str, expected_status: int
    ) -> None:
        membership = self._evaluation_member(access_level)
        self._authenticate(auth_kind, user=membership.user)
        response = self.client.post(self._endpoint(), self._experiment_body(), format="json")
        self.assertEqual(response.status_code, expected_status, response.data)

    @parameterized.expand(
        [
            ("session_object_denied", "session", "viewer", "none", False),
            ("personal_object_denied", "personal_key", "viewer", "none", False),
            ("resource_denied", "session", "none", None, False),
            ("session_object_viewer", "session", "none", "viewer", True),
            ("personal_object_viewer", "personal_key", "none", "viewer", True),
            ("project_key", "project_key", "none", "none", True),
        ]
    )
    def test_references_require_viewer_access(
        self, _name: str, auth_kind: str, resource_access: str, object_access: str | None, allowed: bool
    ) -> None:
        membership = self._evaluation_member()
        dataset_version = self._dataset_item_version()
        definition = ScoreDefinition.objects.create(team=self.team, name="Quality", kind="numeric")
        version = definition.create_new_version(config={"min": 1, "max": 5}, created_by=self.user)
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", access_level=resource_access, organization_member=membership
        )
        if object_access is not None:
            for resource, resource_id in (("dataset", dataset_version.dataset_id), ("llm_analytics", definition.id)):
                AccessControl.objects.create(
                    team=self.team,
                    resource=resource,
                    resource_id=str(resource_id),
                    access_level=object_access,
                    organization_member=membership,
                )
        self._authenticate(auth_kind, user=membership.user)
        body = self._experiment_body() | {"dataset_revision_id": str(dataset_version.dataset_revision_id)}

        created = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(
            created.status_code, status.HTTP_201_CREATED if allowed else status.HTTP_400_BAD_REQUEST, created.data
        )
        if not allowed:
            missing = self.client.post(self._endpoint(), body | {"dataset_revision_id": str(uuid4())}, format="json")
            self.assertEqual(created.data, missing.data)
            self.assertFalse(OfflineExperiment.objects.for_team(self.team.id).exists())
            body = self._experiment_body()
            created = self.client.post(self._endpoint(), body, format="json")
            self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)

        item: dict[str, object] = {"id": str(uuid4())}
        if allowed:
            item["dataset_item_version_id"] = str(dataset_version.id)
        result = {
            "item_id": item["id"],
            "scorer_version_id": str(version.id),
            "status": "ok",
            "value": 2 if allowed else 0,
        }
        uploaded = self.client.post(
            self._endpoint(str(body["id"]), "upload"), {"items": [item], "results": [result]}, format="json"
        )
        self.assertEqual(
            uploaded.status_code, status.HTTP_200_OK if allowed else status.HTTP_400_BAD_REQUEST, uploaded.data
        )
        if allowed:
            self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).get().scorer_version_id, version.id)
        else:
            missing = self.client.post(
                self._endpoint(str(body["id"]), "upload"),
                {"items": [item], "results": [result | {"scorer_version_id": str(uuid4())}]},
                format="json",
            )
            self.assertEqual(uploaded.data, missing.data)
            self.assertFalse(OfflineExperimentItem.objects.for_team(self.team.id).exists())
            self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())

    @parameterized.expand([("session",), ("personal_key",)])
    def test_revoked_reference_access_blocks_new_data_but_allows_retries_and_completion(self, auth_kind: str) -> None:
        membership = self._evaluation_member()
        dataset_version = self._dataset_item_version()
        definition = ScoreDefinition.objects.create(team=self.team, name="Correct", kind="boolean")
        version = definition.create_new_version(config={}, created_by=self.user)
        for resource, resource_id in (("dataset", dataset_version.dataset_id), ("llm_analytics", definition.id)):
            AccessControl.objects.create(
                team=self.team,
                resource=resource,
                resource_id=str(resource_id),
                access_level="viewer",
                organization_member=membership,
            )
        self._authenticate(auth_kind, user=membership.user)
        body = self._experiment_body() | {"dataset_revision_id": str(dataset_version.dataset_revision_id)}
        created = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        experiment_id = str(body["id"])
        item = {"id": str(uuid4()), "dataset_item_version_id": str(dataset_version.id)}
        result = {"item_id": item["id"], "scorer_version_id": str(version.id), "status": "ok", "value": True}
        upload = {"items": [item], "results": [result]}
        accepted = self.client.post(self._endpoint(experiment_id, "upload"), upload, format="json")
        self.assertEqual(accepted.status_code, status.HTTP_200_OK, accepted.data)

        AccessControl.objects.filter(organization_member=membership, resource__in=["dataset", "llm_analytics"]).update(
            access_level="none"
        )
        create_retry = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(create_retry.status_code, status.HTTP_200_OK, create_retry.data)
        self.assertFalse(create_retry.data["created"])
        upload_retry = self.client.post(self._endpoint(experiment_id, "upload"), upload, format="json")
        self.assertEqual(upload_retry.status_code, status.HTTP_200_OK, upload_retry.data)
        self.assertEqual(upload_retry.data["results"][0]["id"], accepted.data["results"][0]["id"])
        self.assertFalse(upload_retry.data["results"][0]["created"])

        next_version = definition.create_new_version(config={}, created_by=self.user)
        new_result = self.client.post(
            self._endpoint(experiment_id, "upload"),
            {"results": [result | {"scorer_version_id": str(next_version.id)}]},
            format="json",
        )
        self.assertEqual(new_result.status_code, status.HTTP_400_BAD_REQUEST, new_result.data)
        self.assertEqual(new_result.data["attr"], "results.0.scorer_version_id")
        new_item_id = str(uuid4())
        new_item = self.client.post(
            self._endpoint(experiment_id, "upload"),
            {"items": [item | {"id": new_item_id}], "results": [result | {"item_id": new_item_id}]},
            format="json",
        )
        self.assertEqual(new_item.status_code, status.HTTP_400_BAD_REQUEST, new_item.data)
        self.assertEqual(new_item.data["attr"], "items")
        self.assertEqual(OfflineExperimentItem.objects.for_team(self.team.id).count(), 1)
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 1)
        completed = self.client.post(self._endpoint(experiment_id, "complete"), {}, format="json")
        self.assertEqual(completed.status_code, status.HTTP_200_OK, completed.data)
        self.assertEqual(completed.data["status"], "completed")

    def test_ingestion_key_cannot_manage_scorers(self) -> None:
        self._authenticate("personal_key")
        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/score_definitions/",
            {"name": "Correct", "kind": "boolean", "config": {"true_label": "Yes", "false_label": "No"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(ScoreDefinition.objects.filter(team=self.team).exists())

    def test_create_validates_the_request_body(self) -> None:
        body = self._experiment_body() | {"run_source": ""}
        response = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(OfflineExperiment.objects.for_team(self.team.id).exists())


class TestOfflineExperimentActionSchemas(SimpleTestCase):
    @parameterized.expand(
        [
            ("upload", {"items", "results"}, {"items", "results"}),
            ("complete", None, {"id", "status", "accepted_item_count", "accepted_result_count"}),
            ("fail", None, {"id", "status", "accepted_item_count", "accepted_result_count"}),
        ]
    )
    def test_action_schema_matches_its_payload(
        self, action: str, request_fields: set[str] | None, response_fields: set[str]
    ) -> None:
        router = SimpleRouter()
        router.register("offline_experiments", OfflineExperimentViewSet, basename="offline_experiments")
        schema = SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)
        operation = schema["paths"][f"/offline_experiments/{{id}}/{action}/"]["post"]
        components = schema["components"]["schemas"]

        if request_fields is None:
            self.assertNotIn("requestBody", operation)
        else:
            request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            self.assertEqual(set(components[request_ref.rsplit("/", 1)[-1]]["properties"]), request_fields)

        response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        self.assertTrue(response_fields <= set(components[response_ref.rsplit("/", 1)[-1]]["properties"]))
