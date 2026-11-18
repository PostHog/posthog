from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Integration, OrganizationMembership, User

from products.access_control.backend.models import AccessControl
from products.customer_analytics.backend.models import (
    FeatureRequestGitHubLink,
    FeatureRequestHistory,
    FeatureRequestHistorySource,
    FeatureRequestStatus,
)
from products.customer_analytics.backend.test.factories import (
    create_account,
    create_feature_request,
    create_feature_request_account_link,
)


class TestFeatureRequestGitHubAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def test_integration_access_controls_github_link_and_history_snapshots(self) -> None:
        account = create_account(team_id=self.team.id)
        request = create_feature_request(team_id=self.team.id, status=FeatureRequestStatus.COMPLETED)
        create_feature_request_account_link(team_id=self.team.id, feature_request=request, account=account)
        integration = Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="installation-1",
            config={},
            sensitive_config={},
        )
        link = FeatureRequestGitHubLink.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            feature_request=request,
            integration=integration,
            installation_id="installation-1",
            repository="posthog/posthog",
            issue_number=42,
            issue_title="Export CSV",
            issue_state="closed",
        )
        FeatureRequestHistory.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            feature_request=request,
            source=FeatureRequestHistorySource.GITHUB,
            actor_id=self.user.id,
            changed_at=timezone.now(),
            changes=[
                {
                    "field": "github_link",
                    "before": None,
                    "after": {
                        "id": str(link.id),
                        "issue_url": "https://github.com/posthog/posthog/issues/42",
                        "repository": "posthog/posthog",
                        "issue_number": 42,
                        "issue_title": "Export CSV",
                        "issue_state": "closed",
                        "sync_enabled": True,
                    },
                },
                {"field": "status", "before": "planned", "after": "completed"},
            ],
        )
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        requests_url = f"/api/projects/{self.team.id}/feature_requests/"
        request_url = f"{requests_url}{request.id}/"

        owner_list = self.client.get(requests_url)
        owner_retrieve = self.client.get(request_url)
        owner_history = self.client.get(f"{request_url}history/")

        self.assertEqual(owner_list.json()["results"][0]["github_link"]["issue_title"], "Export CSV")
        self.assertEqual(owner_retrieve.json()["github_link"]["issue_title"], "Export CSV")
        self.assertEqual([change["field"] for change in owner_history.json()[0]["changes"]], ["github_link", "status"])

        viewer = User.objects.create_and_join(self.organization, "restricted-github-viewer@example.com", "testtest")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        for resource, resource_id in (
            ("customer_analytics", None),
            ("account", str(account.id)),
            ("integration", None),
        ):
            AccessControl.objects.create(
                team=self.team,
                resource=resource,
                resource_id=resource_id,
                access_level="none" if resource == "integration" else "viewer",
                organization_member=membership,
            )
        self.client.force_login(viewer)

        listed = self.client.get(requests_url)
        retrieved = self.client.get(request_url)
        history = self.client.get(f"{request_url}history/")

        self.assertEqual([response.status_code for response in (listed, retrieved, history)], [status.HTTP_200_OK] * 3)
        self.assertIsNone(listed.json()["results"][0]["github_link"])
        self.assertIsNone(retrieved.json()["github_link"])
        self.assertEqual(history.json()[0]["changes"], [{"field": "status", "before": "planned", "after": "completed"}])
        self.assertNotIn("github_link", str(history.json()))
        self.assertNotIn("Export CSV", str(history.json()))
        self.assertNotIn("posthog/posthog", str(history.json()))

        link.integration = None
        link.save(update_fields=["integration"])
        self.assertEqual(
            self.client.get(f"{request_url}history/").json()[0]["changes"],
            [{"field": "status", "before": "planned", "after": "completed"}],
        )
        link.delete()
        self.assertEqual(
            self.client.get(f"{request_url}history/").json()[0]["changes"],
            [{"field": "status", "before": "planned", "after": "completed"}],
        )
