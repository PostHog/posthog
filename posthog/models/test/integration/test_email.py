"""Tests for the native email-sending integration."""

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from disposable_email_domains import blocklist as disposable_email_domains_list
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.integration import EmailIntegration, Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.workflows.backend.providers import SESProvider


class TestEmailIntegrationDomainValidation(BaseTest):
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_successful_domain_creation_ses(self, mock_create_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "successdomain.com"}
        config = {"email": "user@successdomain.com", "name": "Test User", "provider": "ses"}
        integration = EmailIntegration.create_native_integration(
            config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
        )
        assert integration.team == self.team
        assert integration.config["email"] == "user@successdomain.com"
        assert integration.config["provider"] == "ses"
        assert integration.config["domain"] == "successdomain.com"
        assert integration.config["name"] == "Test User"
        assert integration.config["verified"] is False

    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    @patch("products.workflows.backend.providers.SESProvider.verify_email_domain")
    def test_duplicate_domain_in_another_organization(self, mock_create_email_domain, mock_verify_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "successdomain.com"}
        mock_verify_email_domain.return_value = {"status": "verified", "domain": "example.com"}
        # Create an integration with a domain in another organization
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        config = {"email": "user@example.com", "name": "Test User"}
        EmailIntegration.create_native_integration(
            config, team_id=other_team.id, organization_id=str(other_org.id), created_by=self.user
        )

        # Attempt to create the same domain in a different organization should raise ValidationError
        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
            )
        assert "already exists in another organization" in str(exc.value)

    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_duplicate_domain_in_same_organization_allowed(self, mock_create_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "example.com"}
        # Create an integration with a domain in one team
        other_team = Team.objects.create(organization=self.organization, name="other team")
        config = {"email": "user@example.com", "name": "Test User"}
        integration1 = EmailIntegration.create_native_integration(
            config, team_id=other_team.id, organization_id=str(self.organization.id), created_by=self.user
        )

        # Creating the same domain in a different team in the same organization should succeed
        integration2 = EmailIntegration.create_native_integration(
            config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
        )

        assert integration1.config["domain"] == "example.com"
        assert integration2.config["domain"] == "example.com"
        assert integration1.team_id == other_team.id
        assert integration2.team_id == self.team.id

    def test_unsupported_email_domain(self):
        # Test with a free email domain
        config = {"email": "user@gmail.com", "name": "Test User"}

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
            )
        assert "not supported" in str(exc.value)

        # Test with a disposable email domain
        disposable_domain = next(iter(disposable_email_domains_list))
        config = {"email": f"user@{disposable_domain}", "name": "Test User"}

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
            )
        assert disposable_domain in str(exc.value)
        assert "not supported" in str(exc.value)

    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_cross_org_guard_blocks_mixed_case_domain(self, mock_create_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "example.com"}
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        EmailIntegration.create_native_integration(
            {"email": "owner@example.com", "name": "Owner"},
            team_id=other_team.id,
            organization_id=str(other_org.id),
            created_by=self.user,
        )

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                {"email": "attacker@Example.com", "name": "Attacker"},
                team_id=self.team.id,
                organization_id=str(self.organization.id),
                created_by=self.user,
            )
        assert "already exists in another organization" in str(exc.value)

    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_stored_domain_is_lowercased(self, mock_create_email_domain):
        mock_create_email_domain.return_value = {"status": "success", "domain": "successdomain.com"}
        integration = EmailIntegration.create_native_integration(
            {"email": "user@SuccessDomain.COM", "name": "Test User", "provider": "ses"},
            team_id=self.team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )
        assert integration.config["domain"] == "successdomain.com"

    @parameterized.expand(
        [
            ("gmail_titlecase", "user@Gmail.com"),
            ("gmail_uppercase", "user@GMAIL.COM"),
            ("gmail_mixed", "user@gMaIl.cOm"),
            ("yahoo_titlecase", "user@Yahoo.com"),
            ("hotmail_uppercase", "user@HOTMAIL.COM"),
        ]
    )
    def test_free_email_block_is_case_insensitive(self, _name, email):
        config = {"email": email, "name": "Test User"}
        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config,
                team_id=self.team.id,
                organization_id=str(self.organization.id),
                created_by=self.user,
            )
        assert "not supported" in str(exc.value)


class TestEmailIntegrationCrossTenantStaleVerification(BaseTest):
    def _build_ses_provider(self, tenants_for_domain: dict[str, list[str]] | None = None) -> SESProvider:
        patcher = patch("products.workflows.backend.providers.ses.boto3.client")
        patcher.start()
        self.addCleanup(patcher.stop)

        provider = SESProvider()
        provider.ses_client = MagicMock()
        provider.ses_v2_client = MagicMock()
        provider.sts_client = MagicMock()
        provider.sts_client.get_caller_identity.return_value = {"Account": "123456789012"}

        provider.ses_client.verify_domain_identity.return_value = {"VerificationToken": "tok"}
        provider.ses_client.verify_domain_dkim.return_value = {"DkimTokens": ["t1", "t2", "t3"]}
        provider.ses_client.set_identity_mail_from_domain.return_value = {}

        def _list_resource_tenants(ResourceArn: str) -> dict:
            domain = ResourceArn.split("/")[-1]
            return {"ResourceTenants": [{"TenantName": t} for t in (tenants_for_domain or {}).get(domain, [])]}

        provider.ses_v2_client.list_resource_tenants.side_effect = _list_resource_tenants
        return provider

    def _set_global_ses_success(self, provider, domain: str) -> None:
        provider.ses_client.get_identity_verification_attributes.return_value = {
            "VerificationAttributes": {domain: {"VerificationStatus": "Success"}}
        }
        provider.ses_client.get_identity_dkim_attributes.return_value = {
            "DkimAttributes": {domain: {"DkimVerificationStatus": "Success"}}
        }
        provider.ses_client.get_identity_mail_from_domain_attributes.return_value = {
            "MailFromDomainAttributes": {domain: {"MailFromDomainStatus": "Success"}}
        }

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_verify_email_domain_requires_team_tenant_association(self, mock_resolver_cls):
        provider = self._build_ses_provider(tenants_for_domain={"partner.com": ["team-1"]})
        self._set_global_ses_success(provider, "partner.com")
        dmarc_answer = MagicMock()
        dmarc_answer.strings = [b"v=DMARC1; p=none;"]
        mock_resolver_cls.return_value.resolve.return_value = [dmarc_answer]

        result_team_a = provider.verify_email_domain("partner.com", "feedback", team_id=1)
        result_team_b = provider.verify_email_domain("partner.com", "feedback", team_id=999)

        assert result_team_a["status"] == "success"
        assert result_team_b["status"] == "pending"

    @patch("products.workflows.backend.providers.SESProvider.delete_identity")
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_destroy_email_integration_deletes_ses_identity(self, mock_create_email_domain, mock_delete_identity):
        from posthog.api.integration import IntegrationViewSet

        mock_create_email_domain.return_value = {"status": "success"}
        integration = EmailIntegration.create_native_integration(
            {"email": "owner@partner.com", "name": "Owner"},
            team_id=self.team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )

        with self.captureOnCommitCallbacks(execute=True):
            IntegrationViewSet().perform_destroy(integration)

        mock_delete_identity.assert_called_once_with("partner.com")
        assert not Integration.objects.filter(pk=integration.pk).exists()

    @patch("products.workflows.backend.providers.SESProvider.delete_identity")
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_destroy_email_integration_skips_ses_delete_when_sibling_exists(
        self, mock_create_email_domain, mock_delete_identity
    ):
        from posthog.api.integration import IntegrationViewSet

        mock_create_email_domain.return_value = {"status": "success"}
        sibling_team = Team.objects.create(organization=self.organization, name="sibling team")
        EmailIntegration.create_native_integration(
            {"email": "sibling@partner.com", "name": "Sibling"},
            team_id=sibling_team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )
        integration = EmailIntegration.create_native_integration(
            {"email": "owner@partner.com", "name": "Owner"},
            team_id=self.team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )

        with self.captureOnCommitCallbacks(execute=True):
            IntegrationViewSet().perform_destroy(integration)

        assert mock_delete_identity.call_count == 0

    def test_create_email_domain_rejects_foreign_tenant_owner(self):
        provider = self._build_ses_provider(tenants_for_domain={"partner.com": ["team-1"]})

        with pytest.raises(Exception) as exc:
            provider.create_email_domain("partner.com", "feedback", team_id=999, org_team_ids=[999])
        assert "already associated with another organization" in str(exc.value)

    def test_create_email_domain_allows_sibling_team_in_same_org(self):
        provider = self._build_ses_provider(tenants_for_domain={"partner.com": ["team-1"]})

        provider.create_email_domain(
            "partner.com",
            "feedback",
            team_id=2,
            org_team_ids=[1, 2, 3, 4, 5],
        )

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_takeover_after_owner_deletes_integration_is_blocked(self, mock_create_email_domain, mock_resolver_cls):
        from posthog.api.integration import IntegrationViewSet

        mock_create_email_domain.return_value = {"status": "success"}
        dmarc_answer = MagicMock()
        dmarc_answer.strings = [b"v=DMARC1; p=none;"]
        mock_resolver_cls.return_value.resolve.return_value = [dmarc_answer]

        org_a = Organization.objects.create(name="org a")
        team_a = Team.objects.create(organization=org_a, name="team a")
        org_b = Organization.objects.create(name="org b")
        team_b = Team.objects.create(organization=org_b, name="team b")

        integration_a = EmailIntegration.create_native_integration(
            {"email": "owner@partner.com", "name": "Owner A"},
            team_id=team_a.id,
            organization_id=str(org_a.id),
            created_by=self.user,
        )
        with patch("products.workflows.backend.providers.SESProvider.delete_identity") as mock_delete:
            with self.captureOnCommitCallbacks(execute=True):
                IntegrationViewSet().perform_destroy(integration_a)
            mock_delete.assert_called_once_with("partner.com")

        integration_b = EmailIntegration.create_native_integration(
            {"email": "attacker@partner.com", "name": "Attacker B"},
            team_id=team_b.id,
            organization_id=str(org_b.id),
            created_by=self.user,
        )

        provider = self._build_ses_provider(tenants_for_domain={"partner.com": []})
        self._set_global_ses_success(provider, "partner.com")

        email_b = EmailIntegration(integration_b)
        with patch.object(type(email_b), "ses_provider", new=provider):
            result = email_b.verify()

        assert result["status"] == "pending"
        integration_b.refresh_from_db()
        assert integration_b.config.get("verified") is False

    def test_aws_account_id_is_cached_per_provider(self):
        provider = self._build_ses_provider()
        provider.sts_client.get_caller_identity.reset_mock()

        for _ in range(5):
            provider._identity_arn("partner.com")
            provider._identity_arn("other.com")

        assert provider.sts_client.get_caller_identity.call_count == 1


class TestEmailIntegrationSESCleanupOnDelete(BaseTest):
    def _create_email_integration(self, email: str, team_id: int, organization_id: str) -> Integration:
        with patch("products.workflows.backend.providers.SESProvider.create_email_domain"):
            return EmailIntegration.create_native_integration(
                {"email": email, "name": "Test"},
                team_id=team_id,
                organization_id=organization_id,
                created_by=self.user,
            )

    @patch("products.workflows.backend.providers.SESProvider.delete_identity")
    def test_team_cascade_delete_cleans_up_ses_identity(self, mock_delete_identity):
        team = Team.objects.create(organization=self.organization, name="doomed team")
        self._create_email_integration("owner@partner.com", team.id, str(self.organization.id))

        with self.captureOnCommitCallbacks(execute=True):
            team.delete()

        mock_delete_identity.assert_called_once_with("partner.com")

    @patch("products.workflows.backend.providers.SESProvider.delete_identity")
    def test_cascade_delete_skips_ses_cleanup_while_domain_still_in_use(self, mock_delete_identity):
        team = Team.objects.create(organization=self.organization, name="doomed team")
        self._create_email_integration("owner@partner.com", team.id, str(self.organization.id))
        self._create_email_integration("sibling@partner.com", self.team.id, str(self.organization.id))

        with self.captureOnCommitCallbacks(execute=True):
            team.delete()

        mock_delete_identity.assert_not_called()
