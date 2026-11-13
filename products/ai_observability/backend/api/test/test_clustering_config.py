from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.ai_observability.backend.facade.api import clustering_run_context
from products.ai_observability.backend.facade.clustering_contracts import ClusteringRunRef
from products.ai_observability.backend.models.clustering_config import ClusteringConfig
from products.ai_observability.backend.models.clustering_job import ClusteringJob
from products.ai_observability.backend.models.clustering_run import ClusteringRun
from products.ai_observability.backend.tasks.clustering import dispatch_queued_clustering_runs, start_clustering_run
from products.event_definitions.backend.models import PropertyDefinition


class TestClusteringConfigViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

    def test_enabling_queues_one_run_per_job_without_waiting_for_temporal(self):
        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        with patch("products.ai_observability.backend.temporal.clustering_client.dispatch_clustering_run") as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.client.post(url, {"enabled": True}, format="json").status_code, 200)
            dispatch.assert_not_called()
            first_ids = set(ClusteringRun.objects.for_team(self.team.id).values_list("id", flat=True))
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(url, {"enabled": False}, format="json")
                self.client.post(url, {"enabled": True}, format="json")
            self.assertEqual(set(ClusteringRun.objects.for_team(self.team.id).values_list("id", flat=True)), first_ids)
            dispatch.assert_not_called()

    def test_dispatcher_recovers_queued_runs_and_uses_the_same_workflow_after_a_lost_response(self):
        self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        delivered = []
        with patch.object(
            start_clustering_run, "apply_async", side_effect=lambda **kwargs: delivered.append(kwargs["args"])
        ):
            dispatch_queued_clustering_runs()
            dispatch_queued_clustering_runs()
            self.assertEqual(len(delivered), 3)
            ClusteringRun.objects.for_team(self.team.id).update(last_dispatch_at=timezone.now() - timedelta(minutes=2))
            dispatch_queued_clustering_runs()
        self.assertEqual(delivered[:3], delivered[3:])
        client = AsyncMock()
        client.start_workflow.side_effect = [TimeoutError(), None]
        with patch("products.ai_observability.backend.temporal.clustering_client.async_connect", return_value=client):
            start_clustering_run(*delivered[0])
            start_clustering_run(*delivered[3])
        self.assertEqual(
            client.start_workflow.call_args_list[0].kwargs["id"], client.start_workflow.call_args_list[1].kwargs["id"]
        )

    def test_deleted_jobs_do_not_reset_the_project_first_run_budget(self):
        ClusteringConfig.objects.create(team=self.team, enabled=True)
        url = f"/api/projects/{self.team.id}/llm_analytics/clustering_jobs/"
        for i in range(10):
            response = self.client.post(url, {"name": f"Job {i}", "analysis_level": "trace"}, format="json")
            self.assertEqual(response.status_code, 201, response.data)
            self.assertEqual(self.client.delete(f"{url}{response.data['id']}/").status_code, 204)
        response = self.client.post(url, {"name": "Next job", "analysis_level": "trace"}, format="json")
        self.assertEqual(response.status_code, 429, response.data)
        self.assertIn("Retry-After", response)
        self.assertEqual(ClusteringRun.objects.for_team(self.team.id).count(), 10)
        self.assertFalse(ClusteringJob.objects.filter(team=self.team).exists())
        ClusteringRun.objects.for_team(self.team.id).update(created_at=timezone.now() - timedelta(hours=2))
        self.assertEqual(
            self.client.post(url, {"name": "Next job", "analysis_level": "trace"}, format="json").status_code, 201
        )

    def test_enabling_preserves_legacy_filters_in_default_jobs_and_run_snapshots(self):
        filters = [{"key": "$ai_model", "value": "example-model", "operator": "exact", "type": "event"}]
        ClusteringConfig.objects.create(team=self.team, event_filters=filters)
        response = self.client.post(
            f"/api/projects/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(ClusteringJob.objects.filter(team=self.team).values_list("event_filters", flat=True)), [filters] * 3
        )
        self.assertEqual(
            list(ClusteringRun.objects.for_team(self.team.id).values_list("event_filters", flat=True)), [filters] * 3
        )

    @parameterized.expand([("member",), ("role",)])
    def test_restricted_filters_cannot_start_runs_or_expose_existing_progress(self, subject):
        reader = self._create_user("cluster-reader@example.com")
        self.organization.available_product_features = [
            {"name": feature, "key": feature}
            for feature in [AvailableFeature.PROPERTY_ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS]
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="private_property", type=PropertyDefinition.Type.EVENT
        )
        member = reader.organization_memberships.get(organization=self.organization)
        role = Role.objects.create(name="Restricted", organization=self.organization)
        RoleMembership.objects.create(role=role, user=reader, organization_member=member)
        rule = PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=member if subject == "member" else None,
            role=role if subject == "role" else None,
            access_level="none",
        )
        filters = [{"key": "private_property", "type": "event", "operator": "exact", "value": "example"}]
        ClusteringConfig.objects.create(team=self.team, enabled=True)
        url = f"/api/projects/{self.team.id}/llm_analytics/clustering_jobs/"
        response = self.client.post(
            url, {"name": "Filtered", "analysis_level": "evaluation", "event_filters": filters}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        run = ClusteringRun.objects.for_team(self.team.id).get()
        run.status = "waiting"
        run.eligible_count = 1
        run.save()
        self.client.force_login(reader)
        response = self.client.post(
            url, {"name": "Reader job", "analysis_level": "evaluation", "event_filters": filters}, format="json"
        )
        self.assertEqual(response.status_code, 403, response.data)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/llm_analytics/clustering_config/progress/").data, []
        )
        run.job.event_filters = []
        run.job.save()
        self.assertEqual(
            self.client.get(f"/api/projects/{self.team.id}/llm_analytics/clustering_config/progress/").data, []
        )
        run.requested_by = reader
        run.save()
        context = clustering_run_context(ClusteringRunRef(team_id=self.team.id, run_id=str(run.id)))
        self.assertFalse(context.active)
        run.refresh_from_db()
        self.assertEqual(run.status, "canceled")
        rule.delete()
        self.assertEqual(
            len(self.client.get(f"/api/projects/{self.team.id}/llm_analytics/clustering_config/progress/").data), 1
        )

    def test_enable_requires_ai_processing_consent(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ClusteringRun.objects.for_team(self.team.id).exists())

    def test_progress_separates_jobs_and_retry_preserves_the_previous_attempt(self):
        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": True},
            format="json",
        )
        run = ClusteringRun.objects.for_team(self.team.id).get(job__analysis_level="trace")
        run.status = "failed"
        run.eligible_count = 10
        run.save()
        progress_url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/progress/"
        data = self.client.get(progress_url).data
        self.assertEqual(len(data), 3)
        self.assertEqual({job["minimum"] for job in data}, {10})
        self.assertEqual(
            {job["analysis_level"]: job["lookback_days"] for job in data},
            {"trace": 7, "generation": 7, "evaluation": 3},
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/retry/",
            {"job_id": str(run.job_id)},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertEqual(ClusteringRun.objects.for_team(self.team.id).filter(job=run.job, status="queued").count(), 1)

    def test_progress_and_retry_are_scoped_to_the_project(self):
        other_team = Team.objects.create(organization=self.organization, name="Another project")
        other_job = ClusteringJob.objects.create(team=other_team, name="Other traces", analysis_level="trace")
        ClusteringConfig.objects.create(team=self.team, enabled=True)
        self.assertEqual(
            self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/progress/").data, []
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/retry/",
            {"job_id": str(other_job.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(ClusteringRun.objects.for_team(other_team.id).exists())

    def test_projects_are_off_until_explicitly_enabled(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertFalse(response.data["enabled"])
        self.assertFalse(ClusteringJob.objects.filter(team=self.team).exists())

        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        for _ in range(2):
            response = self.client.post(url, {"enabled": True}, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.data["enabled"])
        self.assertCountEqual(
            ClusteringJob.objects.filter(team=self.team, enabled=True).values_list("analysis_level", flat=True),
            ["trace", "generation", "evaluation"],
        )

    def test_disable_and_reenable_preserve_custom_jobs_and_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]
        ClusteringConfig.objects.create(team=self.team, enabled=True, event_filters=filters)
        job = ClusteringJob.objects.create(
            team=self.team, name="Production traces", analysis_level="trace", event_filters=filters
        )
        url = f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/"
        response = self.client.post(url, {"enabled": False}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["enabled"])
        self.assertEqual(response.data["event_filters"], filters)
        job.refresh_from_db()
        self.assertTrue(job.enabled)
        self.client.post(url, {"enabled": True}, format="json")
        self.assertEqual(ClusteringJob.objects.filter(team=self.team, analysis_level="trace").count(), 1)
        job.refresh_from_db()
        self.assertEqual(job.event_filters, filters)

    def test_set_enabled_requires_a_boolean(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_enabled/",
            {"enabled": "please"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(ClusteringConfig.objects.filter(team=self.team, enabled=True).exists())

    def test_unauthenticated_user_cannot_access_config(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_can_get_clustering_config(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn("event_filters", response.data)
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)
        self.assertEqual(response.data["event_filters"], [])

    def test_get_creates_config_if_missing(self):
        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 0)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 1)

    def test_get_returns_existing_config(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 1)
        self.assertEqual(response.data["event_filters"][0]["key"], "ai_product")

    def test_can_set_event_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], filters)

        config = ClusteringConfig.objects.get(team=self.team)
        self.assertEqual(config.event_filters, filters)

    def test_can_clear_event_filters(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], [])

    def test_set_event_filters_requires_event_filters_field(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("event_filters", response.data["detail"].lower())

    def test_set_event_filters_rejects_non_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": "not a list"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("list", response.data["detail"].lower())

    def test_set_event_filters_persists_across_requests(self):
        filters = [
            {"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"},
            {"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"},
        ]

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 2)

    # The default test client uses force_login, which skips the scope check, so these
    # cases use a real Personal API Key — the path MCP and OAuth callers take — to lock
    # the scope the MCP tools must declare (ai_observability_clusters, not llm_analytics).
    @parameterized.expand(
        [
            ("correct_read_scope", ["ai_observability_clusters:read"], status.HTTP_200_OK),
            ("write_scope_grants_read", ["ai_observability_clusters:write"], status.HTTP_200_OK),
            ("wrong_scope_denied", ["llm_analytics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_get_config_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, expected_status)

    # set_event_filters carries its own required_scopes override rather than inheriting
    # scope_object, so it needs separate coverage from the list action above.
    @parameterized.expand(
        [
            ("correct_write_scope", ["ai_observability_clusters:write"], status.HTTP_200_OK),
            ("read_scope_denied", ["ai_observability_clusters:read"], status.HTTP_403_FORBIDDEN),
            ("wrong_scope_denied", ["llm_analytics:write"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_set_event_filters_pak_scope(self, _name: str, scopes: list[str], expected_status: int) -> None:
        api_key = self.create_personal_api_key_with_scopes(scopes)
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {api_key}")
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, expected_status)
