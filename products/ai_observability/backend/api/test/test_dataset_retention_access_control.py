from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.dataset_service import create_dataset, create_dataset_item
from products.ai_observability.backend.models.datasets import Dataset


@pytest.mark.ee
class TestDatasetRetentionAccessControl(APIBaseTest):
    def test_retention_summary_and_renewal_respect_dataset_access(self) -> None:
        self.organization.available_product_features = [
            {"key": feature, "name": feature}
            for feature in (AvailableFeature.ACCESS_CONTROL, AvailableFeature.ROLE_BASED_ACCESS)
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
        )
        viewer = User.objects.create_and_join(self.organization, "viewer@example.com", "testtest")
        visible = create_dataset(team=self.team, name="Visible dataset", created_by=self.user)
        hidden = create_dataset(team=self.team, name="Restricted dataset", created_by=self.user)
        for dataset in (visible, hidden):
            create_dataset_item(team_id=self.team.id, dataset_id=dataset.id, created_by=self.user, input="Example one")
            create_dataset_item(team_id=self.team.id, dataset_id=dataset.id, created_by=self.user, input="Example two")
        Dataset.objects.for_team(self.team.id, canonical=True).filter(id__in=[visible.id, hidden.id]).update(
            last_used_at=timezone.now() - timedelta(days=88)
        )
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", access_level="none", organization_member=membership
        )
        AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=str(visible.id),
            access_level="viewer",
            organization_member=membership,
        )
        self.client.force_login(viewer)
        url = f"/api/projects/{self.team.id}/datasets/"
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True):
            for kind in ("datasets", "revisions"):
                response = self.client.get(f"{url}retention/", {"kind": kind})
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["datasets_count"], 1)
                self.assertEqual(response.data["revisions_count"], 1)
                self.assertEqual([entry["dataset_id"] for entry in response.data["results"]], [str(visible.id)])
            self.assertEqual(
                self.client.post(f"{url}{hidden.id}/extend_retention/", {}).status_code, status.HTTP_403_FORBIDDEN
            )
            self.assertEqual(
                self.client.post(f"{url}{visible.id}/extend_retention/", {"revision": 1}).status_code,
                status.HTTP_200_OK,
            )
