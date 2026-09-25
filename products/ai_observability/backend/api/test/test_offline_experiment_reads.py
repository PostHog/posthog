from datetime import timedelta
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Project, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition


@pytest.mark.ee
class TestOfflineExperimentReads(APIBaseTest):
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
        accepted_at = timezone.now()
        self.experiment = OfflineExperiment.objects.for_team(self.team.id).create(
            id=uuid4(),
            team=self.team,
            name="Arithmetic answers",
            started_at=accepted_at,
            created_at=accepted_at,
            finished_at=accepted_at,
            status="completed",
            expected_item_count=1,
            expected_result_count=1,
            submission_fingerprint="a" * 64,
        )
        self.item = OfflineExperimentItem.objects.for_team(self.team.id).create(
            id=uuid4(),
            team=self.team,
            experiment=self.experiment,
            accepted_at=accepted_at,
            payload_state="available",
            payload_expires_at=accepted_at + timedelta(days=30),
            submission_fingerprint="b" * 64,
        )
        OfflineExperimentItemPayload.objects.for_team(self.team.id).create(
            team=self.team, item=self.item, data={"input": "What is 2 + 2?", "output": "4", "expected_output": None}
        )
        self.definition = ScoreDefinition.objects.create(team=self.team, name="Correct", kind="boolean")
        self.version = self.definition.create_new_version(config={}, created_by=self.user)
        self.result = OfflineEvaluationResult.objects.for_team(self.team.id).create(
            team=self.team,
            item=self.item,
            scorer_definition=self.definition,
            scorer_version=self.version,
            status="ok",
            boolean_value=True,
            accepted_at=accepted_at,
            payload_state="available",
            payload_expires_at=accepted_at + timedelta(days=30),
            submission_fingerprint="c" * 64,
        )
        OfflineEvaluationResultPayload.objects.for_team(self.team.id).create(
            team=self.team, result=self.result, data={"reasoning": "The answer is correct."}
        )

    def _endpoint(self, suffix: str = "", team_id: int | None = None) -> str:
        return f"/api/projects/{team_id or self.team.id}/ai_observability/offline_experiments/{suffix}"

    def _history(self, definition_id: str | None = None, team_id: int | None = None) -> str:
        return (
            f"/api/projects/{team_id or self.team.id}/ai_observability/"
            f"offline_scorers/{definition_id or self.definition.id}/history/"
        )

    def _metadata_paths(self) -> list[str]:
        return [
            self._endpoint(),
            self._endpoint(f"{self.experiment.id}/"),
            self._endpoint(f"{self.experiment.id}/items/"),
            self._endpoint(f"{self.experiment.id}/items/{self.item.id}/"),
            self._endpoint(f"{self.experiment.id}/items/{self.item.id}/payload/"),
        ]

    def _score_paths(self) -> list[str]:
        return [
            self._endpoint(f"{self.experiment.id}/items/{self.item.id}/results/"),
            self._endpoint(f"{self.experiment.id}/results/{self.result.id}/payload/"),
            self._endpoint(f"{self.experiment.id}/scorer_summaries/"),
            self._history(),
        ]

    def _authenticate(
        self, auth_kind: str, scopes: list[str], user: User | None = None, team: Team | None = None
    ) -> None:
        self.client.logout()
        self.client.credentials()
        user = user or self.user
        team = team or self.team
        if auth_kind == "session":
            self.client.force_login(user)
            return
        if auth_kind == "personal_key":
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                user=user,
                label="Offline read test",
                secure_value=hash_key_value(token),
                scopes=scopes,
                scoped_teams=[team.id],
            )
        elif auth_kind == "project_key":
            token = f"phs_{uuid4().hex}"
            ProjectSecretAPIKey.objects.create(
                team=team, label="Offline read test", secure_value=hash_key_value(token), scopes=scopes
            )
        else:
            raise ValueError(auth_kind)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _member(self, evaluation_access: str = "viewer") -> OrganizationMembership:
        user = User.objects.create_and_join(self.organization, "offline-reader@example.com", "test-password")
        membership = OrganizationMembership.objects.get(organization=self.organization, user=user)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
            organization_member=None,
        )
        AccessControl.objects.create(
            team=self.team, resource="evaluation", access_level=evaluation_access, organization_member=membership
        )
        return membership

    @parameterized.expand(
        [
            ("session", "session", [], status.HTTP_200_OK),
            ("personal_reader", "personal_key", ["evaluation:read", "llm_analytics:read"], status.HTTP_200_OK),
            ("personal_uploader", "personal_key", ["offline_evaluation_ingestion:write"], status.HTTP_403_FORBIDDEN),
            ("scorer_only", "personal_key", ["llm_analytics:read"], status.HTTP_403_FORBIDDEN),
            ("project_uploader", "project_key", ["offline_evaluation_ingestion:write"], status.HTTP_403_FORBIDDEN),
            ("project_reader", "project_key", ["evaluation:read", "llm_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_read_routes_enforce_credential_scopes(
        self, _name: str, auth_kind: str, scopes: list[str], expected_status: int
    ) -> None:
        self._authenticate(auth_kind, scopes)
        for path in self._metadata_paths() + self._score_paths():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, expected_status, response.data)

    def test_evaluation_only_key_reads_items_but_cannot_select_or_filter_scorers(self) -> None:
        self._authenticate("personal_key", ["evaluation:read"])
        for path in self._metadata_paths():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        experiment = self.client.get(self._endpoint(f"{self.experiment.id}/")).data
        self.assertEqual(experiment["accepted_item_count"], 1)
        self.assertEqual(experiment["expected_result_count"], 1)
        self.assertIsNone(experiment["visible_result_count"])
        self.assertIsNone(experiment["visible_scorer_definition_count"])
        self.assertIsNone(experiment["visible_scorer_version_count"])
        self.assertFalse(experiment["result_counts_available"])
        self.assertEqual(experiment["result_count_scope"], "unavailable")
        payload = self.client.get(self._endpoint(f"{self.experiment.id}/items/{self.item.id}/payload/")).data
        self.assertTrue(payload["available"])
        self.assertEqual(payload["data"]["input"], "What is 2 + 2?")
        self.assertIsNone(payload["data"]["expected_output"])
        for path in [
            *self._score_paths(),
            self._endpoint(f"?scorer_definition_id={self.definition.id}"),
            self._endpoint(f"{self.experiment.id}/items/?scorer_version_ids={self.version.id}"),
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

    @parameterized.expand([("session",), ("personal_key",)])
    def test_read_routes_require_the_rollout_flag(self, auth_kind: str) -> None:
        self._authenticate(auth_kind, ["evaluation:read", "llm_analytics:read"])
        self.feature_flag.return_value = False
        for path in self._metadata_paths() + self._score_paths():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

    @parameterized.expand([("session",), ("personal_key",)])
    def test_evaluation_permission_is_required_even_with_scorer_access(self, auth_kind: str) -> None:
        membership = self._member("none")
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", access_level="viewer", organization_member=membership
        )
        self._authenticate(auth_kind, ["evaluation:read", "llm_analytics:read"], user=membership.user)
        for path in [self._endpoint(), self._history()]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

    @parameterized.expand([("session",), ("personal_key",)])
    def test_hidden_scorer_results_cannot_be_read_through_other_resources(self, auth_kind: str) -> None:
        membership = self._member()
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", access_level="viewer", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=str(self.definition.id),
            access_level="none",
            organization_member=membership,
        )
        visible = ScoreDefinition.objects.create(team=self.team, name="Resolved", kind="boolean")
        visible_version = visible.create_new_version(config={}, created_by=self.user)
        visible_result = OfflineEvaluationResult.objects.for_team(self.team.id).create(
            team=self.team,
            item=self.item,
            scorer_definition=visible,
            scorer_version=visible_version,
            status="ok",
            boolean_value=False,
            submission_fingerprint="d" * 64,
        )
        self._authenticate(auth_kind, ["evaluation:read", "llm_analytics:read"], user=membership.user)
        experiments = self.client.get(self._endpoint())
        self.assertEqual(experiments.status_code, status.HTTP_200_OK, experiments.data)
        listed = experiments.data["results"][0]
        self.assertEqual(listed["visible_result_count"], 1)
        self.assertEqual(listed["visible_scorer_definition_count"], 1)
        self.assertEqual(listed["visible_scorer_version_count"], 1)
        self.assertEqual(listed["result_count_scope"], "authorized")
        results = self.client.get(self._endpoint(f"{self.experiment.id}/items/{self.item.id}/results/"))
        self.assertEqual(results.status_code, status.HTTP_200_OK, results.data)
        self.assertEqual(results.data["count"], 1)
        self.assertEqual([result["id"] for result in results.data["results"]], [str(visible_result.id)])
        self.assertIs(results.data["results"][0]["value"], False)
        summaries = self.client.get(self._endpoint(f"{self.experiment.id}/scorer_summaries/"))
        self.assertEqual(summaries.status_code, status.HTTP_200_OK, summaries.data)
        self.assertEqual(summaries.data["count"], 1)
        self.assertEqual(summaries.data["results"][0]["scorer"]["definition_id"], str(visible.id))
        hidden_history = self.client.get(self._history())
        missing_history = self.client.get(self._history(str(uuid4())))
        self.assertEqual(hidden_history.status_code, status.HTTP_404_NOT_FOUND, hidden_history.data)
        self.assertEqual(hidden_history.data, missing_history.data)
        hidden_filter = self.client.get(self._endpoint(), {"scorer_definition_id": str(self.definition.id)})
        missing_filter = self.client.get(self._endpoint(), {"scorer_definition_id": str(uuid4())})
        self.assertEqual(hidden_filter.status_code, status.HTTP_404_NOT_FOUND, hidden_filter.data)
        self.assertEqual(hidden_filter.data, missing_filter.data)
        hidden_cells = self.client.get(
            self._endpoint(f"{self.experiment.id}/items/"), {"scorer_version_ids": str(self.version.id)}
        )
        missing_cells = self.client.get(
            self._endpoint(f"{self.experiment.id}/items/"), {"scorer_version_ids": str(uuid4())}
        )
        self.assertEqual(hidden_cells.status_code, status.HTTP_404_NOT_FOUND, hidden_cells.data)
        self.assertEqual(hidden_cells.data, missing_cells.data)
        hidden_payload = self.client.get(self._endpoint(f"{self.experiment.id}/results/{self.result.id}/payload/"))
        self.assertEqual(hidden_payload.status_code, status.HTTP_404_NOT_FOUND, hidden_payload.data)
        visible_history = self.client.get(self._history(str(visible.id)))
        self.assertEqual(visible_history.status_code, status.HTTP_200_OK, visible_history.data)
        self.assertEqual(visible_history.data["count"], 1)

    def test_nested_reads_reject_valid_ids_from_another_experiment(self) -> None:
        other = OfflineExperiment.objects.for_team(self.team.id).create(
            id=uuid4(), team=self.team, name="Other run", started_at=timezone.now(), submission_fingerprint="e" * 64
        )
        for suffix in [
            f"{other.id}/items/{self.item.id}/",
            f"{other.id}/items/{self.item.id}/results/",
            f"{other.id}/items/{self.item.id}/payload/",
            f"{other.id}/results/{self.result.id}/payload/",
        ]:
            with self.subTest(suffix=suffix):
                response = self.client.get(self._endpoint(suffix))
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)

    def test_query_validation_is_wired_into_the_read_endpoint(self) -> None:
        response = self.client.get(self._endpoint(), {"limit": 101})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(response.data["attr"], "limit")

    def test_child_scorer_and_hosted_dataset_can_be_uploaded_and_read_in_the_same_environment(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Child environment")
        sibling = Team.objects.create(organization=self.organization, parent_team=self.team, name="Sibling environment")
        _, unrelated = Project.objects.create_with_team(organization=self.organization, initiating_user=self.user)
        scorer = self.client.post(
            f"/api/projects/{child.id}/llm_analytics/score_definitions/",
            {"name": "Child correctness", "kind": "boolean", "config": {}},
            format="json",
        )
        self.assertEqual(scorer.status_code, status.HTTP_201_CREATED, scorer.data)
        versions = self.client.get(
            f"/api/projects/{child.id}/llm_analytics/score_definitions/{scorer.data['id']}/versions/"
        )
        self.assertEqual(versions.status_code, status.HTTP_200_OK, versions.data)
        self.assertEqual([version["id"] for version in versions.data["results"]], [scorer.data["current_version_id"]])
        dataset = self.client.post(f"/api/projects/{child.id}/datasets/", {"name": "Questions"}, format="json")
        self.assertEqual(dataset.status_code, status.HTTP_201_CREATED, dataset.data)
        dataset_item = self.client.post(
            f"/api/projects/{child.id}/dataset_items/",
            {"dataset": dataset.data["id"], "input": "What is 2 + 2?"},
            format="json",
        )
        self.assertEqual(dataset_item.status_code, status.HTTP_201_CREATED, dataset_item.data)
        experiment_id, item_id = str(uuid4()), str(uuid4())
        created = self.client.post(
            self._endpoint(team_id=child.id),
            {
                "id": experiment_id,
                "name": "Child run",
                "started_at": timezone.now().isoformat(),
                "dataset_revision_id": dataset_item.data["dataset_revision_id"],
            },
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        uploaded = self.client.post(
            self._endpoint(f"{experiment_id}/upload/", team_id=child.id),
            {
                "items": [
                    {
                        "id": item_id,
                        "dataset_item_version_id": dataset_item.data["version_id"],
                        "payload": {"input": "What is 2 + 2?", "output": "4"},
                    }
                ],
                "results": [
                    {
                        "item_id": item_id,
                        "scorer_version_id": scorer.data["current_version_id"],
                        "status": "ok",
                        "value": True,
                        "payload": {"reasoning": "The answer matches."},
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(uploaded.status_code, status.HTTP_200_OK, uploaded.data)
        result_id = uploaded.data["results"][0]["id"]
        completed = self.client.post(self._endpoint(f"{experiment_id}/complete/", team_id=child.id), {}, format="json")
        self.assertEqual(completed.status_code, status.HTTP_200_OK, completed.data)
        child_paths = [
            self._endpoint(f"{experiment_id}/", team_id=child.id),
            self._endpoint(f"{experiment_id}/items/{item_id}/payload/", team_id=child.id),
            self._endpoint(f"{experiment_id}/results/{result_id}/payload/", team_id=child.id),
            self._endpoint(f"{experiment_id}/scorer_summaries/", team_id=child.id),
            self._history(scorer.data["id"], team_id=child.id),
        ]
        for path in child_paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        history = self.client.get(self._history(scorer.data["id"], team_id=child.id))
        self.assertEqual(history.data["count"], 1)
        self.assertEqual(history.data["results"][0]["experiment"]["id"], experiment_id)
        self.assertEqual(history.data["results"][0]["summary"]["status_counts"]["ok"], 1)
        for other_team in [self.team, sibling, unrelated]:
            other_list = self.client.get(self._endpoint(team_id=other_team.id))
            self.assertEqual(other_list.status_code, status.HTTP_200_OK, other_list.data)
            self.assertNotIn(experiment_id, [experiment["id"] for experiment in other_list.data["results"]])
            for child_path in child_paths:
                path = child_path.replace(f"/projects/{child.id}/", f"/projects/{other_team.id}/")
                with self.subTest(path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)

        self._authenticate("personal_key", ["evaluation:read", "llm_analytics:read"], team=child)
        child_list = self.client.get(self._endpoint(team_id=child.id))
        self.assertEqual(child_list.status_code, status.HTTP_200_OK, child_list.data)
        self.assertEqual([experiment["id"] for experiment in child_list.data["results"]], [experiment_id])
        for path in child_paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        parent_through_child = self.client.get(self._endpoint(f"{self.experiment.id}/", team_id=child.id))
        self.assertEqual(parent_through_child.status_code, status.HTTP_404_NOT_FOUND, parent_through_child.data)
        parent_route = self.client.get(self._endpoint(f"{self.experiment.id}/"))
        self.assertEqual(parent_route.status_code, status.HTTP_403_FORBIDDEN, parent_route.data)
