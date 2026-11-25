from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

import responses
from parameterized import parameterized
from rest_framework import status

from posthog.api.organization_integration import BillingDeauthorizationError
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration


class TestOrganizationIntegrationViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.integration_vercel = OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="test-vercel-id",
            config={
                "account": {
                    "name": "Test Vercel Account",
                    "url": "https://vercel.com/test-account",
                }
            },
            created_by=self.user,
        )

    def test_list_organization_integrations_success(self):
        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        integration_data = response.json()["results"][0]
        self.assertEqual(integration_data["kind"], "vercel")
        self.assertEqual(integration_data["integration_id"], "test-vercel-id")
        self.assertEqual(integration_data["config"]["account"]["name"], "Test Vercel Account")
        self.assertEqual(integration_data["created_by"]["id"], self.user.id)
        self.assertIn("created_at", integration_data)
        self.assertIn("updated_at", integration_data)

    def test_list_organization_integrations_multiple_integrations(self):
        OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="second-vercel-id",
            config={"account": {"name": "Second Account"}},
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_organization_integrations_scoped_to_organization(self):
        from posthog.models import Organization

        other_org = Organization.objects.create(name="Other Organization")
        OrganizationIntegration.objects.create(
            organization=other_org,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id="other-org-integration",
            config={},
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["integration_id"], "test-vercel-id")

    def test_list_organization_integrations_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/integrations/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_retrieve_organization_integration_success(self):
        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.integration_vercel.id))
        self.assertEqual(response.json()["kind"], "vercel")
        self.assertEqual(response.json()["integration_id"], "test-vercel-id")

    def test_retrieve_organization_integration_not_found(self):
        url = f"/api/organizations/{self.organization.id}/integrations/00000000-0000-0000-0000-000000000000/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_organization_integration_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_organization_integration(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationIntegration.objects.filter(id=self.integration_vercel.id).exists())

    def test_delete_organization_integration_cleans_up_team_integrations(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        team_integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.id),
            config={"type": "connectable"},
        )

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationIntegration.objects.filter(id=self.integration_vercel.id).exists())
        self.assertFalse(Integration.objects.filter(id=team_integration.id).exists())

    @parameterized.expand(
        [
            (
                "open_invoices",
                status.HTTP_409_CONFLICT,
                "Cannot uninstall billing provider: 1 unpaid invoice must be resolved first.",
                False,
            ),
            ("billing_failure", status.HTTP_502_BAD_GATEWAY, BillingDeauthorizationError.default_detail, True),
        ]
    )
    def test_delete_org_integration_kept_when_billing_deauthorization_fails(
        self, error_kind, expected_status, expected_detail, expect_captured
    ):
        from ee.billing.billing_manager import BillingServiceOpenInvoicesError

        billing_error = (
            BillingServiceOpenInvoicesError(expected_detail)
            if error_kind == "open_invoices"
            else RuntimeError("Billing service returned 500")
        )

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Marketplace installs omit type=connectable; that is what routes through delete_installation.
        self.assertNotEqual(self.integration_vercel.config.get("type"), "connectable")

        team_integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(self.team.id),
            config={"type": "connectable"},
        )

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        with (
            self.is_cloud(True),
            patch(
                "ee.vercel.integration.VercelIntegration.delete_installation",
                side_effect=billing_error,
            ) as mock_delete_installation,
            patch("posthog.api.organization_integration.capture_exception") as mock_capture,
        ):
            response = self.client.delete(url)

        self.assertEqual(response.status_code, expected_status)
        self.assertEqual(response.json()["detail"], expected_detail)
        mock_delete_installation.assert_called_once_with(self.integration_vercel.integration_id)
        self.assertEqual(mock_capture.called, expect_captured)
        # The local integration must survive so the UI disconnect can't sidestep the billing guard.
        self.assertTrue(OrganizationIntegration.objects.filter(id=self.integration_vercel.id).exists())
        self.assertTrue(Integration.objects.filter(id=team_integration.id).exists())

    def test_delete_org_integration_skips_billing_off_cloud(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        with (
            self.is_cloud(False),
            patch(
                "ee.vercel.integration.VercelIntegration.delete_installation",
                side_effect=RuntimeError("Billing service unreachable"),
            ),
        ):
            response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationIntegration.objects.filter(id=self.integration_vercel.id).exists())

    def test_delete_organization_integration_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(OrganizationIntegration.objects.filter(id=self.integration_vercel.id).exists())

    def test_delete_organization_integration_forbidden_for_non_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(OrganizationIntegration.objects.filter(id=self.integration_vercel.id).exists())

    def test_create_organization_integration_not_supported(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        url = f"/api/organizations/{self.organization.id}/integrations/"
        data = {
            "kind": "vercel",
            "integration_id": "new-integration",
            "config": {},
        }
        response = self.client.post(url, data)

        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED))

    def test_update_organization_integration_not_supported(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        url = f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/"
        data = {"config": {"updated": True}}
        response = self.client.patch(url, data)

        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_405_METHOD_NOT_ALLOWED))

    @override_settings(VERCEL_CLIENT_INTEGRATION_ID="client_id", VERCEL_CLIENT_INTEGRATION_SECRET="client_secret")
    @responses.activate
    def test_environment_mapping_is_unchanged_when_vercel_refuses_a_token(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.integration_vercel.config = {"type": "connectable", "environment_mapping": {"production": self.team.pk}}
        self.integration_vercel.save()
        responses.add(
            responses.POST,
            "https://api.vercel.com/v2/oauth/access_token",
            status=400,
            json={"error": {"code": "invalid_client", "message": "Integration disabled"}},
        )

        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/integrations/{self.integration_vercel.id}/environment-mapping/",
            {"production": self.team.pk, "preview": self.team.pk},
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        self.integration_vercel.refresh_from_db()
        assert self.integration_vercel.config["environment_mapping"] == {"production": self.team.pk}
        assert not Integration.objects.filter(team=self.team, kind=Integration.IntegrationKind.VERCEL).exists()
