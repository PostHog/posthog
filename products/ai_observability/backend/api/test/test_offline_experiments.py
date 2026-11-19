from collections.abc import Callable
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
