from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.db import OperationalError, connection
from django.test import SimpleTestCase
from django.utils import timezone

from drf_spectacular.generators import SchemaGenerator
from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ErrorDetail, ValidationError
from rest_framework.routers import SimpleRouter

from posthog.auth import MCP_USER_AGENT_MARKER
from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Project, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.redis import get_client

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.api.offline_experiment_reads import OfflineScorerViewSet
from products.ai_observability.backend.api.offline_experiment_serializers import ResultSubmissionSerializer
from products.ai_observability.backend.api.offline_experiments import OfflineExperimentViewSet
from products.ai_observability.backend.api.score_definitions import ScoreDefinitionViewSet
from products.ai_observability.backend.models.datasets import Dataset, DatasetItem, DatasetItemVersion, DatasetRevision
from products.ai_observability.backend.models.offline_evaluations import (
    OfflineEvaluationResult,
    OfflineEvaluationResultPayload,
    OfflineEvaluationUsageLedger,
    OfflineExperiment,
    OfflineExperimentItem,
    OfflineExperimentItemPayload,
)
from products.ai_observability.backend.models.score_definitions import ScoreDefinition


@pytest.mark.ee
class TestOfflineExperimentsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
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

    def _mutable_run(self) -> tuple[str, str, str, dict]:
        self._authenticate("session")
        experiment = self._experiment_body()
        self.assertEqual(self.client.post(self._endpoint(), experiment).status_code, 201)
        exp_id, item_id = str(experiment["id"]), str(uuid4())
        source = ScoreDefinition.objects.create(team=self.team, name="Accurate", kind="boolean")
        version = source.create_new_version(config={}, created_by=None)
        composite = ScoreDefinition.objects.create(
            team=self.team, name="Total", kind="numeric", calculation="composite"
        )
        computed_version = composite.create_new_version(
            config={"min": 0, "max": 1},
            created_by=None,
            composition={
                "expression": "number(accurate)",
                "inputs": [{"alias": "accurate", "scorer_version_id": str(version.id)}],
            },
        )
        body = {
            "items": [{"id": item_id, "payload": {"input": "A"}}],
            "results": [
                {"item_id": item_id, "scorer_version_id": str(version.id), "status": "error", "error_code": "timeout"},
                {"item_id": item_id, "scorer_version_id": str(computed_version.id), "calculate": True},
            ],
        }
        response = self.client.post(self._endpoint(exp_id, "upload"), body)
        self.assertEqual(response.status_code, 200, response.data)
        return exp_id, item_id, str(response.data["results"][0]["id"]), body

    def test_update_closed_score_recomputes_composite_and_preserves_upload_receipt(self) -> None:
        exp_id, item_id, result_id, body = self._mutable_run()
        close = self.client.post(self._endpoint(exp_id, "complete"), {})
        self.assertEqual(close.status_code, 200)
        url = self._endpoint(exp_id, f"results/{result_id}")
        item_url = self._endpoint(exp_id, f"items/{item_id}")
        before_score_edit = self.client.get(item_url).data["revision"]
        change = {"revision": 0, "status": "ok", "value": True}
        self.assertEqual(self.client.patch(url, change).data, {"revision": 1})
        self.assertEqual(self.client.delete(f"{item_url}?revision={before_score_edit}").status_code, 409)
        self.assertEqual(self.client.patch(url, change).status_code, 409)
        results_url = self._endpoint(exp_id, f"items/{item_id}/results")
        read = self.client.get(results_url).data["results"]
        self.assertEqual(
            {row["scorer"]["name"]: (row["status"], row["value"]) for row in read},
            {"Accurate": ("ok", True), "Total": ("ok", 1.0)},
        )
        payload_url = self._endpoint(exp_id, f"items/{item_id}/payload")
        item_revision = self.client.get(item_url).data["revision"]
        edit = self.client.patch(payload_url, {"revision": item_revision, "payload": {"input": "B"}})
        self.assertEqual(edit.status_code, 200)
        experiment = OfflineExperiment.objects.for_team(self.team.id).get(pk=exp_id)
        last_edit = experiment.updated_at
        self.assertEqual(self.client.patch(url, {"revision": 1, "error_code": None}).data, {"revision": 1})
        self.assertEqual(self.client.get(results_url).data["results"], read)
        self.assertEqual(self.client.get(item_url).data["revision"], edit.data["revision"])
        experiment.refresh_from_db()
        self.assertEqual(experiment.updated_at, last_edit)

        composite = next(row for row in read if row["input_result_ids"])
        self.assertEqual(
            self.client.patch(
                self._endpoint(exp_id, f"results/{composite['id']}"), {"revision": 1, "value": 0}
            ).status_code,
            400,
        )
        retry = self.client.post(self._endpoint(exp_id, "upload"), body)
        self.assertEqual(
            [(r["status"], r["created"]) for r in retry.data["results"]], [("error", False), ("error", False)]
        )
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)), [1]
        )
        self.assertEqual(self.client.delete(f"{url}?revision=1").status_code, 204)
        self.assertEqual(self.client.get(self._endpoint(exp_id, f"items/{item_id}/results")).data["count"], 0)
        self.assertEqual(
            self.client.post(self._endpoint(exp_id, "complete"), {}).data["accepted_result_count"],
            close.data["accepted_result_count"],
        )

    def test_error_code_correction_preserves_score_times_after_an_item_edit(self) -> None:
        exp_id, item_id, result_id, body = self._mutable_run()
        results_url = self._endpoint(exp_id, f"items/{item_id}/results")
        before = {row["id"]: row for row in self.client.get(results_url).data["results"]}
        item_payload_url = self._endpoint(exp_id, f"items/{item_id}/payload")
        self.assertEqual(
            self.client.patch(item_payload_url, {"revision": 0, "payload": {"input": "B"}}).status_code, 200
        )

        result_url = self._endpoint(exp_id, f"results/{result_id}")
        self.assertEqual(
            self.client.patch(result_url, {"revision": 0, "error_code": "invalid_input"}).data, {"revision": 1}
        )
        after = {row["id"]: row for row in self.client.get(results_url).data["results"]}
        self.assertEqual(after[result_id]["score_updated_at"], before[result_id]["score_updated_at"])
        self.assertEqual(after[result_id]["error_code"], "invalid_input")
        composite_id = next(key for key in before if key != result_id)
        self.assertEqual(after[composite_id], before[composite_id])
        retry = self.client.post(self._endpoint(exp_id, "upload"), body)
        self.assertEqual(retry.data["results"][0]["error_code"], "timeout")

    @parameterized.expand(["item", "result"])
    def test_only_direct_api_can_delete_and_reupload_counts_as_new_while_open(self, target: str) -> None:
        exp_id, item_id, result_id, body = self._mutable_run()
        key = f"items/{item_id}" if target == "item" else f"results/{result_id}"
        url = self._endpoint(exp_id, key) + "?revision=0"
        self._authenticate("personal_key", ["evaluation:write", "llm_analytics:read"])
        self.assertEqual(self.client.delete(url, HTTP_USER_AGENT=MCP_USER_AGENT_MARKER).status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())
        self.assertEqual(self.client.post(self._endpoint(exp_id, "upload"), body).status_code, 403)
        self._authenticate("project_key")
        upload = self._endpoint(exp_id, "upload")
        recreated = self.client.post(upload, body)
        self.assertEqual(recreated.status_code, 200, recreated.data)
        self.assertEqual(recreated.data["items"][0]["created"], target == "item")
        self.assertEqual([row["created"] for row in recreated.data["results"]], [True, True])
        retry = self.client.post(upload, body)
        self.assertEqual([row["created"] for row in retry.data["results"]], [False, False])
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)), [1, 1]
        )

    def test_recreated_item_rejects_mutations_for_the_deleted_item(self) -> None:
        exp_id, item_id, _, body = self._mutable_run()
        item_url = self._endpoint(exp_id, f"items/{item_id}")
        first_revision = self.client.get(item_url).data["revision"]
        edit = self.client.patch(item_url, {"revision": first_revision, "trial": "second"})
        self.assertEqual(edit.status_code, 200)
        delete_url = f"{item_url}?revision={edit.data['revision']}"
        self.assertEqual(self.client.delete(delete_url).status_code, 204)
        self.assertEqual(self.client.post(self._endpoint(exp_id, "upload"), body).status_code, 200)

        self.assertEqual(self.client.delete(delete_url).status_code, 409)
        self.assertEqual(self.client.patch(item_url, {"revision": first_revision, "trial": "old"}).status_code, 409)
        replacement = self.client.get(item_url).data
        self.assertIsNone(replacement["trial"])
        self.assertEqual(
            self.client.patch(item_url, {"revision": replacement["revision"], "trial": "new"}).status_code, 200
        )

    def test_payload_update_uses_original_deadline_and_cannot_restore_deleted_data(self) -> None:
        exp_id, item_id, result_id, body = self._mutable_run()
        url = self._endpoint(exp_id, f"items/{item_id}/payload")
        original = self.client.get(url).data
        self.assertEqual(self.client.patch(url, {"revision": 0, "payload": {"output": None}}).data, {"revision": 1})
        updated = self.client.get(url).data
        self.assertEqual(updated["data"], {"input": "A", "output": None})
        self.assertEqual(updated["payload_expires_at"], original["payload_expires_at"])
        item_url = self._endpoint(exp_id, f"items/{item_id}")
        self.assertIsNotNone(self.client.get(item_url).data["content_updated_at"])
        self.assertEqual(self.client.patch(item_url, {"revision": 1, "trial": "second"}).data, {"revision": 2})
        self.assertEqual(self.client.delete(f"{url}?revision=2").status_code, 204)
        self.assertEqual(self.client.get(url).data["data"], None)
        self.assertEqual(self.client.post(self._endpoint(exp_id, "upload"), body).status_code, 200)
        self.assertEqual(self.client.patch(url, {"revision": 3, "payload": {"input": "B"}}).status_code, 409)
        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(pk=result_id)
        payload_url = self._endpoint(exp_id, f"results/{result_id}/payload")
        self.assertEqual(
            self.client.patch(payload_url, {"revision": 0, "payload": {"reasoning": "Late addition"}}).data,
            {"revision": 1},
        )
        self.assertEqual(self.client.delete(f"{item_url}?revision=3").status_code, 409)
        with patch("products.ai_observability.backend.logic.offline_evaluations.mutations.timezone") as clock:
            clock.now.return_value = result.accepted_at + timedelta(days=30)
            self.assertEqual(
                self.client.patch(payload_url, {"revision": 1, "payload": {"reasoning": "Overdue"}}).status_code, 409
            )

    def test_deleted_composite_keeps_its_input_and_cannot_be_reuploaded_after_close(self) -> None:
        exp_id, item_id, _, body = self._mutable_run()
        composite = OfflineEvaluationResult.objects.for_team(self.team.id).get(input_result_ids__isnull=False)
        url = self._endpoint(exp_id, f"results/{composite.pk}") + "?revision=0"
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertEqual(self.client.get(self._endpoint(exp_id, f"items/{item_id}/results")).data["count"], 1)
        upload = self._endpoint(exp_id, "upload")
        self.assertEqual(self.client.post(upload, {"results": body["results"][:1]}).status_code, 200)
        self.assertEqual(self.client.post(self._endpoint(exp_id, "complete"), {}).data["accepted_result_count"], 1)
        self.assertEqual(self.client.post(upload, body).data["code"], "experiment_closed")

    def test_mutating_a_source_requires_access_to_affected_composite(self) -> None:
        exp_id, item_id, result_id, _ = self._mutable_run()
        member = self._evaluation_member()
        composite = ScoreDefinition.objects.get(team=self.team, calculation="composite")
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", access_level="viewer", organization_member=member
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=str(composite.pk),
            access_level="none",
            organization_member=member,
        )
        self._authenticate("personal_key", ["evaluation:write", "llm_analytics:read"], user=member.user)
        self.assertEqual(
            self.client.patch(
                self._endpoint(exp_id, f"results/{result_id}"), {"revision": 0, "value": True, "status": "ok"}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(self._endpoint(exp_id, f"items/{item_id}") + "?revision=0").status_code, 404
        )
        self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), 2)

    def test_composite_from_updated_input_requires_read_access_on_upload_and_replay(self) -> None:
        exp_id, item_id, result_id, body = self._mutable_run()
        result_url = self._endpoint(exp_id, f"results/{result_id}")
        self.assertEqual(self.client.patch(result_url, {"revision": 0, "status": "ok", "value": True}).status_code, 200)
        composite = ScoreDefinition.objects.get(team=self.team, calculation="composite")
        assert composite.current_version is not None
        version = composite.create_new_version(
            config={"min": 0, "max": 1}, created_by=None, composition=composite.current_version.composition
        )
        batch = {
            "results": [
                body["results"][0],
                {"calculate": True, "item_id": item_id, "scorer_version_id": str(version.pk)},
            ]
        }
        url = self._endpoint(exp_id, "upload")
        self._authenticate("personal_key")
        self.assertEqual(self.client.post(url, batch).status_code, 403)
        self._authenticate("session")
        self.assertEqual(self.client.post(url, batch).status_code, 200)
        self._authenticate("project_key")
        self.assertEqual(self.client.post(url, batch).status_code, 403)
        self.assertEqual(self.client.post(url, body).status_code, 200)

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

    @parameterized.expand(
        [
            ("session", "same_upload", [], True),
            ("personal_key", "same_upload", [], True),
            ("project_key", "same_upload", [], True),
            ("session", "stored", [], True),
            ("personal_key", "stored", ["llm_analytics:write"], False),
            ("personal_key", "stored", ["evaluation:read"], False),
            ("personal_key", "stored", ["evaluation:read", "llm_analytics:read"], True),
            ("personal_key", "stored", ["evaluation:write", "llm_analytics:write"], True),
            ("personal_key", "stored", ["*"], True),
            ("project_key", "stored", ["*"], False),
            ("personal_key", "replayed", [], True),
            ("project_key", "replayed", [], True),
            ("personal_key", "partial", [], False),
            *[
                (auth_kind, input_delivery, ["evaluation:read", "llm_analytics:read"], True, revoked_access)
                for auth_kind, input_delivery, revoked_access in [
                    ("session", "stored", "all"),
                    ("personal_key", "same_upload", "all"),
                    ("session", "same_upload", "input"),
                    ("personal_key", "stored", "input"),
                    ("session", "stored", "composite"),
                    ("personal_key", "same_upload", "composite"),
                ]
            ],
        ]
    )
    def test_composite_calculation_upload_and_read_back(
        self,
        auth_kind: str,
        input_delivery: str,
        read_scopes: list[str],
        allowed: bool,
        revoked_access: str | None = None,
    ) -> None:
        inputs = []
        source_configs: list[tuple[str, str, dict[str, object]]] = [
            ("quality", "numeric", {"min": 0, "max": 1}),
            ("safe", "boolean", {}),
            ("relevance", "categorical", {"options": [{"key": "good", "label": "Good"}]}),
        ]
        for alias, kind, config in source_configs:
            source = ScoreDefinition.objects.create(team=self.team, name=alias, kind=kind)
            version = source.create_new_version(config=config, created_by=self.user)
            inputs.append({"alias": alias, "scorer_version_id": str(version.id)})
        self._authenticate("personal_key", ["llm_analytics:write"])
        composites = []
        composite_configs: list[tuple[str, dict[str, object], str]] = [
            ("numeric", {"min": 0, "max": 1}, 'quality * number(safe and "good" in relevance)'),
            ("boolean", {}, 'safe and quality >= 0.8 and "good" in relevance'),
            (
                "categorical",
                {"options": [{"key": "accept", "label": "Accept"}, {"key": "reject", "label": "Reject"}]},
                '"accept" if safe and quality >= 0.8 and "good" in relevance else "reject"',
            ),
            ("numeric", {}, 'quality * number(safe and "good" in relevance) / 0'),
        ]
        for kind, config, expression in composite_configs:
            response = self.client.post(
                f"/api/projects/{self.team.id}/llm_analytics/score_definitions/",
                {
                    "name": kind,
                    "kind": kind,
                    "config": config,
                    "calculation": "composite",
                    "composition": {"inputs": inputs, "expression": expression},
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
            composites.append(response.data["current_version_id"])
        self._authenticate("session")
        experiment = self._experiment_body()
        created = self.client.post(self._endpoint(), experiment, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        item_id = str(uuid4())
        results = [
            {"item_id": item_id, "scorer_version_id": version_id, "calculate": True} for version_id in composites
        ]
        results.extend(
            {"item_id": item_id, "scorer_version_id": source["scorer_version_id"], "status": "ok", "value": value}
            for source, value in zip(inputs, [0.9, True, ["good"]])
        )
        evaluated_at = "2026-01-01T10:00:00Z"
        results[-1]["evaluated_at"] = evaluated_at
        body = {"items": [{"id": item_id}], "results": results}
        upload_url = self._endpoint(str(experiment["id"]), "upload")
        if input_delivery != "same_upload":
            sources = self.client.post(
                upload_url, {"items": body["items"], "results": results[len(composites) :]}, format="json"
            )
            self.assertEqual(sources.status_code, status.HTTP_200_OK, sources.data)
        if input_delivery == "stored":
            body["results"] = results[: len(composites)]
        elif input_delivery == "partial":
            body["results"] = results[:-1]
        self._authenticate(auth_kind, ["offline_evaluation_ingestion:write", *read_scopes])
        response = self.client.post(upload_url, body, format="json")
        if not allowed:
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
            self.assertEqual(OfflineEvaluationResult.objects.for_team(self.team.id).count(), len(inputs))
            return
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        source_ids = {
            result["id"]
            for result in (
                sources.data["results"] if input_delivery == "stored" else response.data["results"][len(composites) :]
            )
        }
        self.assertEqual(
            [(row["status"], row["error_code"]) for row in response.data["results"]],
            [("ok", None)] * 3
            + [("error", "composite_formula_error")]
            + ([("ok", None)] * 3 if input_delivery != "stored" else []),
        )
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)), [3]
        )
        completed = self.client.post(self._endpoint(str(experiment["id"]), "complete"), {}, format="json")
        self.assertEqual(completed.status_code, status.HTTP_200_OK, completed.data)
        replay = self.client.post(upload_url, body, format="json")
        self.assertEqual(replay.status_code, status.HTTP_200_OK, replay.data)
        self.assertEqual(
            [result["id"] for result in replay.data["results"]], [result["id"] for result in response.data["results"]]
        )
        self.assertTrue(all(not result["created"] for result in replay.data["results"]))
        self.assertEqual(replay.data["results"][3]["status"], "error")
        self.assertEqual(replay.data["results"][3]["error_code"], "composite_formula_error")
        if input_delivery == "replayed":
            changed_inputs = [dict(result) for result in results]
            changed_inputs[len(composites)]["value"] = 0.5
            conflict = self.client.post(upload_url, {"items": [], "results": changed_inputs}, format="json")
            self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT, conflict.data)
        if auth_kind != "session" and not read_scopes:
            self.assertEqual(
                self.client.get(self._endpoint(str(experiment["id"]), f"items/{item_id}/results")).status_code, 403
            )
            composite_only_retry = self.client.post(
                upload_url, {"items": [], "results": results[: len(composites)]}, format="json"
            )
            self.assertEqual(composite_only_retry.status_code, status.HTTP_403_FORBIDDEN, composite_only_retry.data)
        self._authenticate("personal_key", ["evaluation:read", "llm_analytics:read"])
        read = self.client.get(self._endpoint(str(experiment["id"]), f"items/{item_id}/results"))
        self.assertEqual(read.status_code, status.HTTP_200_OK, read.data)
        derived = {
            result["scorer"]["id"]: result
            for result in read.data["results"]
            if result["scorer"]["calculation"] == "composite"
        }
        self.assertEqual(set(derived), set(composites))
        for version_id, value in zip(composites, [0.9, True, ["accept"], None]):
            self.assertEqual(derived[version_id]["value"], value)
            self.assertEqual(derived[version_id]["score_updated_at"], evaluated_at)
            self.assertEqual(set(derived[version_id]["input_result_ids"]), source_ids)
            self.assertEqual(len(derived[version_id]["scorer"]["composition"]["inputs"]), 3)
        summaries = self.client.get(self._endpoint(str(experiment["id"]), "scorer_summaries"))
        self.assertEqual(summaries.status_code, status.HTTP_200_OK, summaries.data)
        self.assertEqual(len(summaries.data["results"]), 7)

        if revoked_access is not None:
            membership = self._evaluation_member()
            access = AccessControl.objects.create(
                team=self.team,
                resource="llm_analytics",
                access_level="viewer",
                organization_member=membership,
            )
            self._authenticate(auth_kind, ["offline_evaluation_ingestion:write", *read_scopes], user=membership.user)
            permitted_retry = self.client.post(upload_url, body, format="json")
            self.assertEqual(permitted_retry.status_code, status.HTTP_200_OK, permitted_retry.data)
            self.assertEqual(permitted_retry.data, replay.data)

            if revoked_access == "all":
                access.access_level = "none"
                access.save()
            else:
                version_id = inputs[0]["scorer_version_id"] if revoked_access == "input" else composites[0]
                definition = ScoreDefinition.objects.get(team=self.team, current_version_id=version_id)
                AccessControl.objects.create(
                    team=self.team,
                    resource="llm_analytics",
                    resource_id=str(definition.id),
                    access_level="none",
                    organization_member=membership,
                )

            denied_retry = self.client.post(upload_url, body, format="json")
            self.assertEqual(denied_retry.status_code, status.HTTP_400_BAD_REQUEST, denied_retry.data)
            self.assertEqual(
                denied_retry.data["attr"],
                "results.0.calculate" if revoked_access == "input" else "results.0.scorer_version_id",
            )
            self.assertNotIn("results", denied_retry.data)

    @parameterized.expand([("session", False), ("personal_key", False), ("project_key", False), ("session", True)])
    @patch("products.ai_observability.backend.api.offline_experiments.report_user_action")
    def test_ingestion_and_both_lifecycle_actions(
        self, auth_kind: str, analytics_failure: bool, report_action: Mock
    ) -> None:
        if analytics_failure:
            report_action.side_effect = RuntimeError("Analytics unavailable")
        definition = ScoreDefinition.objects.create(team=self.team, name="Correct", kind="boolean")
        version = definition.create_new_version(config={"true_label": "Yes", "false_label": "No"}, created_by=self.user)
        other_definition = ScoreDefinition.objects.create(team=self.team, name="Relevant", kind="boolean")
        other_version = other_definition.create_new_version(
            config={"true_label": "Yes", "false_label": "No"}, created_by=self.user
        )
        self._authenticate(auth_kind)
        body = self._experiment_body() | {
            "expected_item_count": 2,
            "expected_result_count": 4,
            "dataset_source": "https://private.example.com/datasets/customer-evals",
        }
        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        experiment_id = str(body["id"])
        self.assertEqual(created.data["id"], experiment_id)
        expected_author = None if auth_kind == "project_key" else self.user.pk
        self.assertEqual(
            OfflineExperiment.objects.for_team(self.team.id).get(pk=experiment_id).created_by_id, expected_author
        )
        with self.captureOnCommitCallbacks(execute=True):
            incomplete = self.client.post(self._endpoint(experiment_id, "complete"), {}, format="json")
        self.assertEqual(incomplete.status_code, status.HTTP_409_CONFLICT, incomplete.data)
        self.assertEqual(incomplete.data["code"], "expected_count_mismatch")
        self.assertEqual(incomplete.data["expected_item_count"], 2)
        self.assertEqual(incomplete.data["expected_result_count"], 4)
        self.assertEqual(incomplete.data["accepted_item_count"], 0)
        self.assertEqual(incomplete.data["accepted_result_count"], 0)

        item_ids = [str(uuid4()), str(uuid4())]
        upload_body = {
            "items": [{"id": item_id, "payload": {"input": "What is 2 + 2?", "output": "5"}} for item_id in item_ids],
            "results": [
                {"item_id": item_id, "scorer_version_id": str(scorer_version.id), "status": "ok", "value": False}
                for item_id in item_ids
                for scorer_version in (version, other_version)
            ],
        }
        with self.captureOnCommitCallbacks(execute=True):
            uploaded = self.client.post(self._endpoint(experiment_id, "upload"), upload_body, format="json")
        self.assertEqual(uploaded.status_code, status.HTTP_200_OK, uploaded.data)
        result = OfflineEvaluationResult.objects.for_team(self.team.id).get(pk=uploaded.data["results"][0]["id"])
        self.assertIs(result.boolean_value, False)
        self.assertEqual(result.scorer_version_id, version.id)

        with self.captureOnCommitCallbacks(execute=True):
            completed = self.client.post(self._endpoint(experiment_id, "complete"), {}, format="json")
        self.assertEqual(completed.status_code, status.HTTP_200_OK, completed.data)
        self.assertEqual(completed.data["status"], "completed")
        self.assertEqual(completed.data["accepted_item_count"], 2)
        self.assertEqual(completed.data["accepted_result_count"], 4)

        failed_body = self._experiment_body() | {"expected_result_count": 10}
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(
                self.client.post(self._endpoint(), failed_body, format="json").status_code, status.HTTP_201_CREATED
            )
            failed = self.client.post(self._endpoint(str(failed_body["id"]), "fail"), {}, format="json")
        self.assertEqual(failed.status_code, status.HTTP_200_OK, failed.data)
        self.assertEqual(failed.data["status"], "failed")
        self.assertEqual(failed.data["accepted_result_count"], 0)

        self._authenticate("project_key" if auth_kind != "project_key" else "session")
        with self.captureOnCommitCallbacks(execute=True):
            retried = self.client.post(self._endpoint(), body, format="json")
            upload_retry = self.client.post(self._endpoint(experiment_id, "upload"), upload_body, format="json")
            complete_retry = self.client.post(self._endpoint(experiment_id, "complete"), {}, format="json")
            fail_retry = self.client.post(self._endpoint(str(failed_body["id"]), "fail"), {}, format="json")
        self.assertEqual(retried.status_code, status.HTTP_200_OK)
        self.assertEqual(upload_retry.status_code, status.HTTP_200_OK)
        self.assertEqual(complete_retry.status_code, status.HTTP_200_OK)
        self.assertEqual(fail_retry.status_code, status.HTTP_200_OK)
        self.assertEqual(
            OfflineExperiment.objects.for_team(self.team.id).get(pk=experiment_id).created_by_id, expected_author
        )
        self.assertEqual(
            [call.args[1] for call in report_action.call_args_list],
            [
                "llma offline experiment created",
                "llma offline experiment results uploaded",
                "llma offline experiment completed",
                "llma offline experiment created",
                "llma offline experiment failed",
            ],
        )
        upload_event = report_action.call_args_list[1]
        self.assertEqual(
            upload_event.args[2],
            {"experiment_id": experiment_id, "created_item_count": 2, "created_result_count": 4},
        )
        completed_event = report_action.call_args_list[2]
        self.assertEqual(report_action.call_args_list[0].args[2]["dataset_source"], "external")
        self.assertEqual(completed_event.args[2]["dataset_source"], "external")
        self.assertEqual(report_action.call_args_list[3].args[2]["dataset_source"], "unknown")
        self.assertEqual(report_action.call_args_list[4].args[2]["dataset_source"], "unknown")
        for call in report_action.call_args_list:
            self.assertNotIn(body["dataset_source"], call.args[2].values())
        self.assertEqual(completed_event.args[2]["status"], "completed")
        self.assertEqual(completed_event.args[2]["accepted_item_count"], 2)
        self.assertEqual(completed_event.args[2]["accepted_result_count"], 4)
        self.assertEqual(completed_event.kwargs["team"], self.team)
        self.assertEqual(completed_event.args[0], completed_event.kwargs["request"].user)
        self.assertTrue(completed_event.args[0].distinct_id)

    @parameterized.expand(
        [("ledger", status.HTTP_500_INTERNAL_SERVER_ERROR), ("quota", status.HTTP_402_PAYMENT_REQUIRED)]
    )
    def test_rejected_mixed_upload_preserves_existing_results_and_can_retry(
        self, rejection: str, expected_status: int
    ) -> None:
        definition = ScoreDefinition.objects.create(team=self.team, name="Correct", kind="boolean")
        version = definition.create_new_version(config={}, created_by=self.user)
        self._authenticate("project_key")
        body = self._experiment_body()
        created = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        endpoint = self._endpoint(str(body["id"]), "upload")
        items = [
            {"id": str(uuid4()), "payload": {"input": "What is 2 + 2?", "output": "4"}},
            {"id": str(uuid4()), "payload": {"input": "What is 3 + 3?", "output": "6"}},
        ]
        results = [
            {
                "item_id": item["id"],
                "scorer_version_id": str(version.id),
                "status": "ok",
                "value": True,
                "payload": {"reasoning": "The answer is correct."},
            }
            for item in items
        ]
        accepted = self.client.post(endpoint, {"items": items[:1], "results": results[:1]}, format="json")
        self.assertEqual(accepted.status_code, status.HTTP_200_OK, accepted.data)
        rows_before_failure = {
            model: list(model.objects.for_team(self.team.id).values())
            for model in (
                OfflineExperimentItem,
                OfflineEvaluationResult,
                OfflineExperimentItemPayload,
                OfflineEvaluationResultPayload,
                OfflineEvaluationUsageLedger,
            )
        }

        def fail_ledger_insert(
            execute: Callable[..., object], sql: str, params: object, many: bool, context: object
        ) -> object:
            if sql.startswith("INSERT INTO") and OfflineEvaluationUsageLedger._meta.db_table in sql:
                raise OperationalError("Ledger insert failed")
            return execute(sql, params, many, context)

        upload = {"items": items, "results": results}
        if rejection == "ledger":
            with connection.execute_wrapper(fail_ledger_insert):
                failed = self.client.post(endpoint, upload, format="json")
        else:
            redis_client = get_client()
            quota_key = "@posthog/quota-limits/llm_events"
            redis_client.zadd(quota_key, {self.team.api_token: timezone.now().timestamp() + 3600})
            self.addCleanup(redis_client.zrem, quota_key, self.team.api_token)
            replayed = self.client.post(endpoint, {"items": items[:1], "results": results[:1]}, format="json")
            self.assertEqual(replayed.status_code, status.HTTP_200_OK, replayed.data)
            self.assertEqual(replayed.data["results"][0], accepted.data["results"][0] | {"created": False})
            failed = self.client.post(endpoint, upload, format="json")
            self.assertEqual(failed.data["code"], "quota_limit_exceeded", failed.data)
            redis_client.zadd(quota_key, {self.team.api_token: timezone.now().timestamp() - 1})

        self.assertEqual(failed.status_code, expected_status, failed.data)
        for model, rows in rows_before_failure.items():
            self.assertEqual(list(model.objects.for_team(self.team.id).values()), rows)

        retried = self.client.post(endpoint, upload, format="json")
        self.assertEqual(retried.status_code, status.HTTP_200_OK, retried.data)
        self.assertEqual(retried.data["results"][0], accepted.data["results"][0] | {"created": False})
        self.assertTrue(retried.data["results"][1]["created"])
        for model in rows_before_failure:
            self.assertEqual(model.objects.for_team(self.team.id).count(), 2)
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)),
            [1, 1],
        )

        replayed = self.client.post(endpoint, upload, format="json")
        self.assertEqual(replayed.status_code, status.HTTP_200_OK, replayed.data)
        self.assertEqual(replayed.data["results"], [result | {"created": False} for result in retried.data["results"]])
        self.assertEqual(
            list(OfflineEvaluationUsageLedger.objects.for_team(self.team.id).values_list("quantity", flat=True)),
            [1, 1],
        )

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
    @patch("products.ai_observability.backend.api.offline_experiments.report_user_action")
    def test_references_require_viewer_access(
        self,
        _name: str,
        auth_kind: str,
        resource_access: str,
        object_access: str | None,
        allowed: bool,
        report_action: Mock,
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

        with self.captureOnCommitCallbacks(execute=True):
            created = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(
            created.status_code, status.HTTP_201_CREATED if allowed else status.HTTP_400_BAD_REQUEST, created.data
        )
        if allowed:
            self.assertEqual(report_action.call_args.args[2]["dataset_source"], "posthog")
        else:
            report_action.assert_not_called()
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

    def test_upload_reports_all_invalid_scores_without_accepting_any_entries(self) -> None:
        definition = ScoreDefinition.objects.create(team=self.team, name="Accuracy", kind="numeric")
        version = definition.create_new_version(config={"min": 0, "max": 1}, created_by=self.user)
        body = self._experiment_body()
        created = self.client.post(self._endpoint(), body, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        items = [{"id": str(uuid4()), "payload": {"input": "What is 2 + 2?"}} for _ in range(3)]
        response = self.client.post(
            self._endpoint(str(body["id"]), "upload"),
            {
                "items": items,
                "results": [
                    {"item_id": item["id"], "scorer_version_id": str(version.id), "status": "ok", "value": value}
                    for item, value in zip(items, [0.5, -0.1, 1.1])
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(
            response.data["errors"],
            [
                {
                    "code": "invalid_input",
                    "detail": "Ensure this value is greater than or equal to 0.",
                    "attr": "results.1.value",
                },
                {
                    "code": "invalid_input",
                    "detail": "Ensure this value is less than or equal to 1.",
                    "attr": "results.2.value",
                },
            ],
        )
        self.assertEqual(response.data["attr"], "results.1.value")
        self.assertFalse(OfflineExperimentItem.objects.for_team(self.team.id).exists())
        self.assertFalse(OfflineEvaluationResult.objects.for_team(self.team.id).exists())


class TestOfflineExperimentValidationErrors(SimpleTestCase):
    @parameterized.expand(
        [
            ("value", 0.5),
            ("status", "error"),
            ("error_code", "custom_error"),
            ("payload", {"reasoning": "Caller result"}),
            ("evaluator_trace_id", "evaluator-trace"),
            ("evaluated_at", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_calculation_request_rejects_caller_supplied_result(self, field: str, value: object) -> None:
        serializer = ResultSubmissionSerializer(
            data={"item_id": str(uuid4()), "scorer_version_id": str(uuid4()), "calculate": True, field: value}
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("calculate", serializer.errors)

    @parameterized.expand(
        [
            (
                "nested_batch_fields",
                ValidationError(
                    {
                        "results": [
                            {},
                            {"value": [ErrorDetail("A score is required.", code="required")]},
                            {
                                "scorer_version_id": [
                                    ErrorDetail("Provide a UUID.", code="invalid"),
                                    ErrorDetail("Identifier is too short.", code="min_length"),
                                ]
                            },
                        ]
                    }
                ),
                [
                    {"code": "required", "detail": "A score is required.", "attr": "results.1.value"},
                    {"code": "invalid_input", "detail": "Provide a UUID.", "attr": "results.2.scorer_version_id"},
                    {
                        "code": "min_length",
                        "detail": "Identifier is too short.",
                        "attr": "results.2.scorer_version_id",
                    },
                ],
            ),
            (
                "scalar",
                ValidationError("Provide an object."),
                [{"code": "invalid_input", "detail": "Provide an object.", "attr": None}],
            ),
            (
                "non_field_errors",
                ValidationError({"non_field_errors": ["Provide an item or result.", "The request is empty."]}),
                [
                    {"code": "invalid_input", "detail": "Provide an item or result.", "attr": None},
                    {"code": "invalid_input", "detail": "The request is empty.", "attr": None},
                ],
            ),
            (
                "nested_non_field_errors",
                ValidationError({"items": [{}, {}, {"non_field_errors": ["Provide an item object."]}]}),
                [{"code": "invalid_input", "detail": "Provide an item object.", "attr": "items.2"}],
            ),
        ]
    )
    def test_validation_errors_preserve_every_message_and_field_path(
        self, _name: str, exception: ValidationError, expected: list[dict[str, str | None]]
    ) -> None:
        response = OfflineExperimentViewSet().handle_exception(exception)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {"type": "validation_error", **expected[0], "errors": expected})


class TestOfflineExperimentActionSchemas(SimpleTestCase):
    def test_patch_requires_revision_and_payload_for_payload_routes(self) -> None:
        router = SimpleRouter()
        router.register("offline_experiments", OfflineExperimentViewSet, basename="offline_experiments")
        schema = SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)
        for resource in ["items/{item_id}", "results/{result_id}"]:
            for suffix, required in [("", ["revision"]), ("/payload", ["payload", "revision"])]:
                path = f"/offline_experiments/{{id}}/{resource}{suffix}/"
                with self.subTest(path=path):
                    body = schema["paths"][path]["patch"]["requestBody"]
                    self.assertTrue(body["required"])
                    ref = body["content"]["application/json"]["schema"]["$ref"]
                    self.assertCountEqual(schema["components"]["schemas"][ref.rsplit("/", 1)[-1]]["required"], required)

    def test_read_pages_are_object_envelopes_instead_of_arrays_of_pages(self) -> None:
        router = SimpleRouter()
        router.register("offline_experiments", OfflineExperimentViewSet, basename="offline_experiments")
        router.register("offline_scorers", OfflineScorerViewSet, basename="offline_scorers")
        router.register("score_definitions", ScoreDefinitionViewSet, basename="score_definitions")
        schema = SchemaGenerator(patterns=router.urls).get_schema(request=None, public=True)
        components = schema["components"]["schemas"]

        for path in [
            "/offline_experiments/",
            "/offline_experiments/{id}/items/",
            "/offline_experiments/{id}/items/{item_id}/results/",
            "/offline_experiments/{id}/scorer_summaries/",
            "/offline_scorers/{id}/history/",
            "/score_definitions/{id}/versions/",
        ]:
            with self.subTest(path=path):
                response_schema = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
                    "schema"
                ]
                self.assertIn("$ref", response_schema)
                page_schema = components[response_schema["$ref"].rsplit("/", 1)[-1]]
                self.assertEqual(page_schema["type"], "object")
                self.assertTrue(
                    {"count", "next", "previous", "next_cursor", "results"} <= set(page_schema["properties"])
                )
                self.assertEqual(page_schema["properties"]["results"]["type"], "array")

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
