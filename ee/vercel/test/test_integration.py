from typing import Any

from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from rest_framework.exceptions import NotFound, ValidationError

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team
from posthog.models.user import User

from ee.vercel.integration import VercelIntegration


class TestVercelIntegration(TestCase):
    def setUp(self):
        self.installation_id = "inst_123456789"
        self.user = User.objects.create_user(email="test@example.com", password="testpass", first_name="Test")
        self.organization = Organization.objects.create(name="Test Org")
        self.user.join(organization=self.organization, level=OrganizationMembership.Level.OWNER)

        self.installation = OrganizationIntegration.objects.create(
            organization=self.organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            integration_id=self.installation_id,
            config={"billing_plan_id": "free", "scopes": ["read"]},
            created_by=self.user,
        )

        self.payload: dict[str, Any] = {
            "scopes": ["read", "write"],
            "acceptedPolicies": {"toc": "2024-02-28T10:00:00Z"},
            "credentials": {"access_token": "token", "token_type": "Bearer"},
            "account": {
                "name": "Test Account",
                "url": "https://example.com",
                "contact": {"email": "contact@example.com", "name": "John Doe"},
            },
        }

    def test_get_installation_exists(self):
        installation = VercelIntegration._get_installation(self.installation_id)
        assert installation.integration_id == self.installation_id
        assert installation.organization == self.organization

    def test_get_installation_not_found(self):
        with self.assertRaises(NotFound) as context:
            VercelIntegration._get_installation("inst_nonexistent")
        assert str(context.exception) == "Installation not found"

    def test_get_vercel_plans_structure(self):
        plans = VercelIntegration.get_vercel_plans()
        assert len(plans) == 2

        free_plan = next(p for p in plans if p["id"] == "free")
        assert free_plan["type"] == "subscription"
        assert free_plan["name"] == "Free"
        assert not free_plan["paymentMethodRequired"]

        paid_plan = next(p for p in plans if p["id"] == "pay_as_you_go")
        assert paid_plan["type"] == "subscription"
        assert paid_plan["name"] == "Pay-as-you-go"
        assert paid_plan["paymentMethodRequired"]

    def test_get_installation_returns_free_plan(self):
        result = VercelIntegration.get_installation_billing_plan(self.installation_id)
        assert "billingplan" in result
        assert result["billingplan"]["id"] == "free"

    def test_update_installation_success(self):
        VercelIntegration.update_installation(self.installation_id, "pro200")

        updated_installation = OrganizationIntegration.objects.get(integration_id=self.installation_id)
        assert updated_installation.config["billing_plan_id"] == "free"

    def test_update_installation_not_found(self):
        VercelIntegration.update_installation("inst_nonexistent", "pro200")

    @patch("django.conf.settings.DEBUG", True)
    def test_delete_installation_dev_mode(self):
        result = VercelIntegration.delete_installation(self.installation_id)

        assert result["finalized"]
        assert not OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists()

    @patch("django.conf.settings.DEBUG", False)
    def test_delete_installation_prod_mode(self):
        result = VercelIntegration.delete_installation(self.installation_id)

        assert not result["finalized"]
        assert not OrganizationIntegration.objects.filter(integration_id=self.installation_id).exists()

    def test_delete_installation_not_found(self):
        with self.assertRaises(NotFound):
            VercelIntegration.delete_installation("inst_nonexistent")

    def test_get_product_plans_posthog(self):
        result = VercelIntegration.get_product_plans("posthog")
        assert "plans" in result
        assert len(result["plans"]) == 2

    def test_get_product_plans_invalid_product(self):
        with self.assertRaises(NotFound) as context:
            VercelIntegration.get_product_plans("invalid_product")
        assert str(context.exception) == "Product not found"

    def test_upsert_installation_existing_installation(self):
        original_config = self.installation.config.copy()

        VercelIntegration.upsert_installation(self.installation_id, self.payload)

        self.installation.refresh_from_db()
        assert self.installation.config == self.payload
        assert self.installation.config != original_config

    @patch("ee.vercel.integration.report_user_signed_up")
    def test_upsert_installation_new_user_new_org(self, mock_report):
        new_installation_id = "inst_987654321"

        VercelIntegration.upsert_installation(new_installation_id, self.payload)

        new_installation = OrganizationIntegration.objects.get(integration_id=new_installation_id)
        assert new_installation.config == self.payload

        new_user = User.objects.get(email=self.payload["account"]["contact"]["email"])
        assert new_user.first_name == self.payload["account"]["contact"]["name"]
        assert not new_user.is_email_verified

        new_org = new_installation.organization
        assert new_org.name == self.payload["account"]["name"]

        membership = OrganizationMembership.objects.get(user=new_user, organization=new_org)
        assert membership.level == OrganizationMembership.Level.OWNER

        mock_report.assert_called_once()

    @patch("ee.vercel.integration.report_user_signed_up")
    def test_upsert_installation_existing_user_new_org(self, mock_report):
        existing_user = User.objects.create_user(
            email=self.payload["account"]["contact"]["email"], password="existing", first_name="Existing"
        )
        new_installation_id = "inst_987654321"

        VercelIntegration.upsert_installation(new_installation_id, self.payload)

        new_installation = OrganizationIntegration.objects.get(integration_id=new_installation_id)
        assert new_installation.created_by == existing_user

        new_org = new_installation.organization
        membership = OrganizationMembership.objects.get(user=existing_user, organization=new_org)
        assert membership.level == OrganizationMembership.Level.OWNER

        mock_report.assert_not_called()

    @patch("ee.vercel.integration.capture_exception")
    def test_upsert_installation_integrity_error(self, mock_capture):
        with patch("posthog.models.organization.Organization.objects.create") as mock_create:
            mock_create.side_effect = IntegrityError("Duplicate key")

            with self.assertRaises(ValidationError) as context:
                VercelIntegration.upsert_installation("inst_new", self.payload)

            detail = context.exception.detail
            if isinstance(detail, dict):
                assert detail.get("validation_error") == "Something went wrong."
            mock_capture.assert_called_once()

    def test_upsert_installation_creates_org_with_fallback_name(self):
        new_installation_id = "inst_987654321"
        payload_without_name = self.payload.copy()
        del payload_without_name["account"]["name"]

        VercelIntegration.upsert_installation(new_installation_id, payload_without_name)

        new_installation = OrganizationIntegration.objects.get(integration_id=new_installation_id)
        assert new_installation.organization.name == f"Vercel Installation {new_installation_id}"

    def test_upsert_installation_creates_user_with_fallback_name(self):
        new_installation_id = "inst_987654321"
        payload_without_name = self.payload.copy()
        del payload_without_name["account"]["contact"]["name"]

        VercelIntegration.upsert_installation(new_installation_id, payload_without_name)

        new_user = User.objects.get(email=payload_without_name["account"]["contact"]["email"])
        assert new_user.first_name == ""

    def test_get_resource_exists(self):
        team = Team.objects.create(organization=self.organization, name="Test Team")
        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": "Test Resource"},
            created_by=self.user,
        )

        result = VercelIntegration._get_resource(str(resource.pk))
        assert result.pk == resource.pk
        assert result.team == team

    def test_get_resource_not_found(self):
        with self.assertRaises(NotFound):
            VercelIntegration._get_resource("123123")

    def test_create_resource(self):
        resource_data = {
            "productId": "posthog",
            "name": "New Resource",
            "metadata": {"key": "value"},
            "billingPlanId": "free",
        }

        result = VercelIntegration.create_resource(self.installation_id, resource_data)

        assert "id" in result
        assert result["productId"] == "posthog"
        assert result["name"] == "New Resource"
        assert result["metadata"] == {"key": "value"}
        assert result["status"] == "ready"
        assert "secrets" in result
        assert "billingPlan" in result

        resource = Integration.objects.get(pk=result["id"])
        assert resource.config == resource_data

    def test_get_resource_with_installation(self):
        team = Team.objects.create(organization=self.organization, name="Test Team")
        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": "Test Resource", "metadata": {}},
            created_by=self.user,
        )

        result = VercelIntegration.get_resource(str(resource.pk), self.installation_id)

        assert result["id"] == str(resource.pk)
        assert result["productId"] == "posthog"
        assert result["name"] == "Test Resource"
        assert result["status"] == "ready"
        assert "secrets" in result
        assert "billingPlan" in result

    def test_update_resource(self):
        team = Team.objects.create(organization=self.organization, name="Test Team")
        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": "Original Name", "metadata": {"old": "value"}},
            created_by=self.user,
        )

        update_data = {"name": "Updated Name", "metadata": {"new": "value"}}
        result = VercelIntegration.update_resource(str(resource.pk), self.installation_id, update_data)

        resource.refresh_from_db()
        assert resource.config["name"] == "Updated Name"
        assert resource.config["metadata"] == {"new": "value"}
        assert resource.config["productId"] == "posthog"
        assert result["name"] == "Updated Name"
        assert result["metadata"] == {"new": "value"}

    def test_delete_resource(self):
        team = Team.objects.create(organization=self.organization, name="Test Team")
        resource = Integration.objects.create(
            team=team,
            kind=Integration.IntegrationKind.VERCEL,
            integration_id=str(team.pk),
            config={"productId": "posthog", "name": "Test Resource"},
            created_by=self.user,
        )
        resource_id = str(resource.pk)
        VercelIntegration.delete_resource(resource_id)
        assert not Integration.objects.filter(pk=resource_id).exists()

    def test_delete_resource_not_found(self):
        with self.assertRaises(NotFound):
            VercelIntegration.delete_resource("999999")

    def test_build_secrets(self):
        team = Team.objects.create(organization=self.organization, name="Test Team", api_token="test_api_token")
        secrets = VercelIntegration._build_secrets(team)

        assert len(secrets) == 2
        assert secrets[0]["name"] == "POSTHOG_PROJECT_API_KEY"
        assert secrets[0]["value"] == "test_api_token"
        assert secrets[1]["name"] == "POSTHOG_HOST"
        assert (
            secrets[1]["value"] == "https://us.posthog.com"
        )  # TODO: Make region dependent when we have region support
