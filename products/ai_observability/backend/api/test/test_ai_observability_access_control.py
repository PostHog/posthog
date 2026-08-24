import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.ai_observability.backend.dataset_service import archive_dataset, create_dataset, create_dataset_item
from products.ai_observability.backend.models.clustering_job import ClusteringJob
from products.ai_observability.backend.models.provider_keys import LLMProviderKey
from products.ai_observability.backend.models.review_queues import ReviewQueue, ReviewQueueItem
from products.ai_observability.backend.models.trace_reviews import TraceReview

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


_DEFAULT_MODEL_CONFIGURATION = {
    "provider": "openai",
    "model": "gpt-5-mini",
    "provider_key_id": None,
}


@pytest.mark.ee
class TestAIObservabilityAccessControl(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
            {
                "key": AvailableFeature.ROLE_BASED_ACCESS,
                "name": AvailableFeature.ROLE_BASED_ACCESS,
            },
        ]
        self.organization.save()
        feature_flag_patch = patch(
            "posthog.permissions.posthog_feature_flag_enabled",
            return_value=True,
        )
        feature_flag_patch.start()
        self.addCleanup(feature_flag_patch.stop)

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
            organization_member=None,
            role=None,
        )

        self.viewer_user = User.objects.create_and_join(self.organization, "viewer@posthog.com", "testtest")
        self.editor_user = User.objects.create_and_join(self.organization, "editor@posthog.com", "testtest")
        self.no_access_user = User.objects.create_and_join(self.organization, "noaccess@posthog.com", "testtest")

        self.dataset = create_dataset(
            team=self.team,
            name="Test Dataset",
            created_by=self.user,
        )

        self.provider_key = LLMProviderKey.objects.create(
            team=self.team,
            provider="openai",
            name="Test Key",
            encrypted_config={"api_key": "sk-test123"},
            state=LLMProviderKey.State.OK,
            created_by=self.user,
        )

        self.trace_review = TraceReview.objects.create(
            team=self.team,
            trace_id="trace_123",
            created_by=self.user,
            reviewed_by=self.user,
        )
        self.review_queue = ReviewQueue.objects.create(
            team=self.team,
            name="Support queue",
            created_by=self.user,
        )
        self.review_queue_item = ReviewQueueItem.objects.create(
            team=self.team,
            queue=self.review_queue,
            trace_id="trace_pending",
            created_by=self.user,
        )

        self.clustering_job = ClusteringJob.objects.create(
            team=self.team,
            name="Test Clustering Job",
            analysis_level="trace",
            event_filters=[],
            enabled=True,
        )

    def _set_access_level(self, user: User, resource: str = "llm_analytics", access_level: str = "viewer") -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=None,
            access_level=access_level,
            organization_member=membership,
        )

    def _set_project_admin_access(self, user: User) -> None:
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="admin",
            organization_member=membership,
        )

    def _mutate_provider_key(self, action: str):
        if action == "create":
            return self.client.post(
                f"/api/environments/{self.team.id}/llm_analytics/provider_keys/",
                {
                    "provider": "openai",
                    "name": "New Key",
                    "api_key": "sk-test456",
                },
                format="json",
            )

        if action == "update":
            return self.client.patch(
                f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{self.provider_key.id}/",
                {"name": "Updated Key"},
                format="json",
            )

        if action == "validate":
            return self.client.post(
                f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{self.provider_key.id}/validate/"
            )

        if action == "delete":
            return self.client.delete(
                f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{self.provider_key.id}/"
            )

        raise ValueError(f"Unsupported action: {action}")

    # -- Viewer can list/retrieve --

    @parameterized.expand(
        [
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_viewer_can_list(self, endpoint, _attr):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_viewer_can_export_an_archived_dataset(self, _async_connect: AsyncMock) -> None:
        create_dataset_item(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            created_by=self.user,
            input={"question": "Can a viewer export this?"},
        )
        archive_dataset(team_id=self.team.id, dataset_id=self.dataset.id)
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/{self.dataset.id}/exports/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand(
        [
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_viewer_can_retrieve(self, endpoint, attr):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        obj = getattr(self, attr)
        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/{obj.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("products.ai_observability.backend.api.ai_blob.object_storage.read_object")
    def test_viewer_can_fetch_ai_blob(self, mock_read):
        mock_read.return_value = (b"png-bytes", "image/png")
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/projects/{self.team.id}/ai_blob/v1/sha256/{'a' * 64}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_score_definitions(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/score_definitions/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_trace_reviews(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_review_queues(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/review_queues/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_review_queue_items(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_clustering_config(self):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_list_clustering_jobs(self):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_can_retrieve_clustering_job(self):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/{self.clustering_job.id}/"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # -- Viewer cannot create/update/delete --

    def test_viewer_cannot_create_dataset(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "New Dataset"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_provider_key(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/provider_keys/{self.provider_key.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_score_definition(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/score_definitions/",
            {
                "name": "Quality",
                "kind": "categorical",
                "config": {"options": [{"key": "good", "label": "Good"}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/",
            {"trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
            {"comment": "Updated"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_trace_review(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/",
            {"name": "New queue"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
            {"name": "Renamed queue"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_review_queue(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/",
            {"queue_id": str(self.review_queue.id), "trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        alternate_queue = ReviewQueue.objects.create(team=self.team, name="Bug bash", created_by=self.user)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
            {"queue_id": str(alternate_queue.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_review_queue_item(self):
        self._set_access_level(self.viewer_user, access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_create_clustering_job(self):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/",
            {"name": "New Job", "analysis_level": "trace", "event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_update_clustering_job(self):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/{self.clustering_job.id}/",
            {"name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_delete_clustering_job(self):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/{self.clustering_job.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_cannot_set_clustering_config_event_filters(self):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.ai_observability.backend.api.clustering.sync_connect")
    def test_viewer_cannot_trigger_clustering_run(self, mock_connect, _mock_flag):
        self._set_access_level(self.viewer_user, resource="ai_observability_clusters", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_runs/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        mock_connect.assert_not_called()

    # -- Editor can create/update/delete --

    def test_editor_can_create_dataset(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "Editor Dataset"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_dataset_specific_editor_can_create_item(self):
        inaccessible_dataset = create_dataset(
            team=self.team,
            name="Another Dataset",
            created_by=self.user,
        )
        self._set_access_level(self.editor_user, access_level="none")
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=str(self.dataset.id),
            access_level="editor",
            organization_member=membership,
        )
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(self.dataset.id), "input": {"question": "Can I edit this dataset?"}},
            format="json",
        )
        inaccessible_response = self.client.post(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(inaccessible_dataset.id), "input": {"question": "Can I edit this dataset?"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(inaccessible_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dataset_item_operations_use_parent_dataset_access(self):
        item = create_dataset_item(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            created_by=self.user,
            input={"question": "Can I see this?"},
        )
        inaccessible_dataset = create_dataset(
            team=self.team,
            name="Inaccessible Dataset",
            created_by=self.user,
        )
        self._set_access_level(self.editor_user, access_level="none")
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        dataset_access = AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=str(self.dataset.id),
            access_level="viewer",
            organization_member=membership,
        )
        self.client.force_login(self.editor_user)

        list_response = self.client.get(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(self.dataset.id)},
        )
        inaccessible_list_response = self.client.get(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(inaccessible_dataset.id)},
        )
        retrieve_response = self.client.get(
            f"/api/environments/{self.team.id}/dataset_items/{item.item.id}/",
        )
        blocked_update_response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{item.item.id}/",
            {"base_version": 1, "input": {"question": "Blocked"}},
            format="json",
        )

        self.assertEqual([result["id"] for result in list_response.data["results"]], [str(item.item.id)])
        self.assertEqual(inaccessible_list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(blocked_update_response.status_code, status.HTTP_403_FORBIDDEN)

        dataset_access.access_level = "editor"
        dataset_access.save(update_fields=["access_level"])
        allowed_update_response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{item.item.id}/",
            {"base_version": 1, "input": {"question": "Allowed"}},
            format="json",
        )
        self.assertEqual(allowed_update_response.status_code, status.HTTP_200_OK)

    def test_dataset_item_write_access_is_checked_on_the_exact_parent(self):
        editable_item = create_dataset_item(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            created_by=self.user,
            input={"question": "Editable"},
        )
        view_only_dataset = create_dataset(
            team=self.team,
            name="View-only Dataset",
            created_by=self.user,
        )
        view_only_item = create_dataset_item(
            team_id=self.team.id,
            dataset_id=view_only_dataset.id,
            created_by=self.user,
            input={"question": "View only"},
        )
        self._set_access_level(self.editor_user, access_level="none")
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=str(self.dataset.id),
            access_level="editor",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=str(view_only_dataset.id),
            access_level="viewer",
            organization_member=membership,
        )
        self.client.force_login(self.editor_user)

        editable_response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{editable_item.item.id}/",
            {"base_version": 1, "input": {"question": "Updated"}},
            format="json",
        )
        view_only_response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{view_only_item.item.id}/",
            {"base_version": 1, "input": {"question": "Blocked"}},
            format="json",
        )

        self.assertEqual(editable_response.status_code, status.HTTP_200_OK)
        self.assertEqual(view_only_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dataset_access_controls_can_be_updated(self):
        membership = OrganizationMembership.objects.get(user=self.viewer_user, organization=self.organization)

        response = self.client.put(
            f"/api/environments/{self.team.id}/datasets/{self.dataset.id}/access_controls/",
            {
                "access_level": "viewer",
                "organization_member": str(membership.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            AccessControl.objects.filter(
                team=self.team,
                resource="dataset",
                resource_id=str(self.dataset.id),
                organization_member=membership,
                access_level="viewer",
            ).exists()
        )

    @parameterized.expand(
        [
            ("create", status.HTTP_403_FORBIDDEN),
            ("update", status.HTTP_403_FORBIDDEN),
            ("validate", status.HTTP_403_FORBIDDEN),
            ("delete", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_editor_cannot_mutate_provider_key_without_project_admin(self, action, expected_status):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        with patch("products.ai_observability.backend.api.provider_keys.validate_provider_key") as mock_validate:
            mock_validate.return_value = (LLMProviderKey.State.OK, None)
            response = self._mutate_provider_key(action)
        self.assertEqual(response.status_code, expected_status)

    @parameterized.expand(
        [
            ("create", status.HTTP_201_CREATED),
            ("update", status.HTTP_200_OK),
            ("validate", status.HTTP_200_OK),
            ("delete", status.HTTP_204_NO_CONTENT),
        ]
    )
    def test_project_admin_can_mutate_provider_key_without_llm_analytics_access(self, action, expected_status):
        self._set_project_admin_access(self.editor_user)
        self.client.force_login(self.editor_user)

        with patch("products.ai_observability.backend.api.provider_keys.validate_provider_key") as mock_validate:
            mock_validate.return_value = (LLMProviderKey.State.OK, None)
            response = self._mutate_provider_key(action)
        self.assertEqual(response.status_code, expected_status)

    def test_editor_can_create_score_definition(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/score_definitions/",
            {
                "name": "Quality",
                "kind": "categorical",
                "config": {"options": [{"key": "good", "label": "Good"}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_create_trace_review(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/",
            {"trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_trace_review(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
            {"comment": "Updated by editor"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_trace_review(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/trace_reviews/{self.trace_review.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_create_review_queue(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/",
            {"name": "Escalations"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_review_queue(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
            {"name": "Renamed queue"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_review_queue(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queues/{self.review_queue.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_create_review_queue_item(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/",
            {"queue_id": str(self.review_queue.id), "trace_id": "trace_new"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_review_queue_item(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        alternate_queue = ReviewQueue.objects.create(team=self.team, name="Bug bash", created_by=self.user)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
            {"queue_id": str(alternate_queue.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_review_queue_item(self):
        self._set_access_level(self.editor_user, access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/review_queue_items/{self.review_queue_item.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_create_clustering_job(self):
        self._set_access_level(self.editor_user, resource="ai_observability_clusters", access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/",
            {"name": "Editor Job", "analysis_level": "trace", "event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_editor_can_update_clustering_job(self):
        self._set_access_level(self.editor_user, resource="ai_observability_clusters", access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/{self.clustering_job.id}/",
            {"name": "Renamed by editor"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_editor_can_delete_clustering_job(self):
        self._set_access_level(self.editor_user, resource="ai_observability_clusters", access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.delete(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/{self.clustering_job.id}/",
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_editor_can_set_clustering_config_event_filters(self):
        self._set_access_level(self.editor_user, resource="ai_observability_clusters", access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthoganalytics.feature_enabled", return_value=True)
    @patch("products.ai_observability.backend.api.clustering.sync_connect")
    def test_editor_can_trigger_clustering_run(self, mock_connect, _mock_flag):
        mock_client = AsyncMock()
        mock_client.start_workflow = AsyncMock(return_value=AsyncMock(id="wf-1", result_run_id="run-1"))
        mock_connect.return_value = mock_client

        self._set_access_level(self.editor_user, resource="ai_observability_clusters", access_level="editor")
        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_runs/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    # -- None access blocks everything --

    @parameterized.expand(
        [
            ("datasets",),
            ("llm_analytics/provider_keys",),
            ("llm_analytics/review_queues",),
            ("llm_analytics/review_queue_items",),
        ]
    )
    def test_none_access_blocks_list(self, endpoint):
        self._set_access_level(self.no_access_user, access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @parameterized.expand(
        [
            ("llm_analytics/clustering_jobs",),
            ("llm_analytics/clustering_config",),
        ]
    )
    def test_none_ai_observability_clusters_access_blocks_list(self, endpoint):
        self._set_access_level(self.no_access_user, resource="ai_observability_clusters", access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("products.ai_observability.backend.api.ai_blob.object_storage.read_object")
    def test_none_access_blocks_ai_blob(self, mock_read):
        mock_read.return_value = (b"png-bytes", "image/png")
        self._set_access_level(self.no_access_user, access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(f"/api/projects/{self.team.id}/ai_blob/v1/sha256/{'a' * 64}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Resource inheritance: setting llm_analytics cascades to child resources --

    @parameterized.expand(
        [
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_llm_analytics_viewer_can_list_child_resources(self, endpoint, _attr):
        self._set_access_level(self.viewer_user, resource="llm_analytics", access_level="viewer")
        self.client.force_login(self.viewer_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            ("datasets", "dataset"),
            ("llm_analytics/provider_keys", "provider_key"),
        ]
    )
    def test_llm_analytics_none_blocks_child_resource_list(self, endpoint, _attr):
        self._set_access_level(self.no_access_user, resource="llm_analytics", access_level="none")
        self.client.force_login(self.no_access_user)

        response = self.client.get(f"/api/environments/{self.team.id}/{endpoint}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- ai_observability_clusters is independent from llm_analytics (not a child resource) --

    def test_llm_analytics_editor_does_not_grant_clustering_access(self):
        self._set_access_level(self.editor_user, resource="llm_analytics", access_level="editor")
        self._set_access_level(self.editor_user, resource="ai_observability_clusters", access_level="none")
        self.client.force_login(self.editor_user)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_ai_observability_clusters_editor_without_llm_analytics_access(self):
        self._set_access_level(self.editor_user, resource="llm_analytics", access_level="none")
        self._set_access_level(self.editor_user, resource="ai_observability_clusters", access_level="editor")
        self.client.force_login(self.editor_user)

        clustering_response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_jobs/")
        self.assertEqual(clustering_response.status_code, status.HTTP_200_OK)

        datasets_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        self.assertEqual(datasets_response.status_code, status.HTTP_403_FORBIDDEN)

    # -- Org admin has full access without explicit permissions --

    def test_org_admin_has_full_access(self):
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()

        self.client.force_login(self.editor_user)

        response = self.client.post(
            f"/api/environments/{self.team.id}/evaluations/",
            {
                "name": "Admin Evaluation",
                "evaluation_type": "llm_judge",
                "model_configuration": _DEFAULT_MODEL_CONFIGURATION,
                "evaluation_config": {"prompt": "prompt"},
                "output_type": "boolean",
                "output_config": {},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_org_admin_can_access_private_dataset_and_items(self):
        item = create_dataset_item(
            team_id=self.team.id,
            dataset_id=self.dataset.id,
            created_by=self.user,
            input={"question": "Can an admin see this?"},
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=str(self.dataset.id),
            access_level="none",
            organization_member=None,
            role=None,
        )
        membership = OrganizationMembership.objects.get(user=self.editor_user, organization=self.organization)
        membership.level = OrganizationMembership.Level.ADMIN
        membership.save()
        self.client.force_login(self.editor_user)

        dataset_list_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        item_retrieve_response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/{item.item.id}/")

        self.assertIn(str(self.dataset.id), [result["id"] for result in dataset_list_response.data["results"]])
        self.assertEqual(item_retrieve_response.status_code, status.HTTP_200_OK)
