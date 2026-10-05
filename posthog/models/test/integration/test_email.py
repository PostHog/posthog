"""Tests for the native email-sending integration."""

from collections.abc import Callable, Mapping

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from disposable_email_domains import blocklist as disposable_email_domains_list
from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models.integration import EmailIntegration, Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team


def email_domain_flag(*, organization_id: str | None = None, distinct_id: str | None = None) -> Callable[..., bool]:
    def feature_enabled(
        key: str,
        flag_distinct_id: str,
        groups: Mapping[str, str] | None = None,
        group_properties: Mapping[str, Mapping[str, str]] | None = None,
        **_kwargs,
    ) -> bool:
        organization_matches = (groups or {}).get("organization") == organization_id and (group_properties or {}).get(
            "organization", {}
        ).get("id") == organization_id
        return key == "workflows-email-domain-agent-setup" and (organization_matches or flag_distinct_id == distinct_id)

    return feature_enabled


class TestEmailIntegrationDomainValidation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag_patcher = patch(
            "posthoganalytics.feature_enabled", side_effect=email_domain_flag(organization_id=str(self.organization.id))
        )
        self.feature_enabled: MagicMock = flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
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

    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
    @patch("products.workflows.backend.facade.api.verify_ses_email_domain")
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

    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
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

    @parameterized.expand(
        [
            ("omitted_label", "bounce", None, "bounce"),
            ("matching_label", "bounce", "bounce", "bounce"),
            ("default_label_on_a_legacy_blank_domain", "", "feedback", "feedback"),
        ]
    )
    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
    def test_new_sender_keeps_the_domain_mail_from_label(
        self, _name, domain_label, requested_label, expected_label, mock_create_email_domain
    ):
        other_team = Team.objects.create(organization=self.organization, name="other team")
        Integration.objects.create(
            team=other_team,
            kind="email",
            integration_id="sender@example.com",
            config={"email": "sender@example.com", "domain": "example.com", "mail_from_subdomain": domain_label},
        )
        config = {"email": "new@example.com", "name": "New", "provider": "ses"}
        if requested_label is not None:
            config["mail_from_subdomain"] = requested_label

        integration = EmailIntegration.create_native_integration(
            config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
        )

        assert integration.config["mail_from_subdomain"] == expected_label
        assert mock_create_email_domain.call_args.kwargs["mail_from_subdomain"] == expected_label

    @parameterized.expand(
        [
            ("different_label", ["bounce"], "feedback", "MAIL FROM subdomain 'bounce'"),
            ("label_matching_one_of_conflicting_senders", ["bounce", "feedback"], "feedback", "different MAIL FROM"),
            ("omitted_label_with_conflicting_senders", ["bounce", "feedback"], None, "different MAIL FROM"),
        ]
    )
    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
    def test_new_sender_cannot_move_the_domain_mail_from_label(
        self, _name, existing_labels, requested_label, expected_error, mock_create_email_domain
    ):
        other_team = Team.objects.create(organization=self.organization, name="other team")
        for index, label in enumerate(existing_labels):
            Integration.objects.create(
                team=other_team,
                kind="email",
                integration_id=f"sender{index}@example.com",
                config={"email": f"sender{index}@example.com", "domain": "example.com", "mail_from_subdomain": label},
            )
        config = {"email": "new@example.com", "name": "New", "provider": "ses"}
        if requested_label is not None:
            config["mail_from_subdomain"] = requested_label

        with pytest.raises(ValidationError) as exc:
            EmailIntegration.create_native_integration(
                config, team_id=self.team.id, organization_id=str(self.organization.id), created_by=self.user
            )

        assert expected_error in str(exc.value)
        mock_create_email_domain.assert_not_called()
        assert not Integration.objects.filter(integration_id="new@example.com").exists()

    @parameterized.expand([("rolled_out_to_the_organization", False), ("enabled_for_the_acting_user", True)])
    @patch("products.workflows.backend.facade.api.verify_ses_email_domain", return_value={"status": "pending"})
    @patch("products.workflows.backend.facade.api.update_ses_mail_from_subdomain")
    def test_verifying_any_sender_keeps_a_changed_mail_from_label(
        self, _name, flag_targets_user, mock_update_mail_from_subdomain, mock_verify_email_domain
    ):
        if flag_targets_user:
            self.feature_enabled.side_effect = email_domain_flag(distinct_id=self.user.distinct_id)
        other_team = Team.objects.create(organization=self.organization, name="other team")
        senders = {
            email: Integration.objects.create(
                team=team,
                kind="email",
                integration_id=email,
                config={
                    "email": email,
                    "domain": email.split("@")[1],
                    "mail_from_subdomain": label,
                    "provider": "ses",
                },
            )
            for team, email, label in [
                (self.team, "edited@example.com", "feedback"),
                (self.team, "teammate@example.com", "feedback"),
                (other_team, "sibling@example.com", "returns"),
                (self.team, "unrelated@other.com", "feedback"),
            ]
        }

        EmailIntegration(senders["edited@example.com"], acting_user=self.user).update_native_integration(
            {"mail_from_subdomain": "bounce"}, team_id=self.team.id
        )
        mock_update_mail_from_subdomain.assert_called_once_with("example.com", mail_from_subdomain="bounce")

        verified_labels = {}
        for email, sender in senders.items():
            EmailIntegration(sender, acting_user=self.user).verify()
            verified_labels[email] = mock_verify_email_domain.call_args.kwargs["mail_from_subdomain"]
        assert verified_labels == {
            "edited@example.com": "bounce",
            "teammate@example.com": "bounce",
            "sibling@example.com": "bounce",
            "unrelated@other.com": "feedback",
        }

    @parameterized.expand([("label_omitted", {"name": "Renamed"}), ("label_cleared", {"mail_from_subdomain": ""})])
    @patch("products.workflows.backend.facade.api.update_ses_mail_from_subdomain")
    def test_editing_a_sender_without_a_label_keeps_the_current_domain_label(
        self, _name, edit, mock_update_mail_from_subdomain
    ):
        senders = [
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=email,
                config={"email": email, "domain": "example.com", "mail_from_subdomain": "feedback", "provider": "ses"},
            )
            for email in ["renamed@example.com", "relabeled@example.com"]
        ]
        renamed_as_loaded = EmailIntegration(Integration.objects.get(pk=senders[0].pk))

        EmailIntegration(senders[1]).update_native_integration({"mail_from_subdomain": "bounce"}, team_id=self.team.id)
        renamed_as_loaded.update_native_integration(edit, team_id=self.team.id)

        assert mock_update_mail_from_subdomain.call_args.kwargs["mail_from_subdomain"] == "bounce"
        assert Integration.objects.get(pk=senders[1].pk).config["mail_from_subdomain"] == "bounce"

    @parameterized.expand([("explicit_labels", "feedback", "returns"), ("omitted_and_blank_labels", None, "")])
    @patch("products.workflows.backend.facade.api.verify_ses_email_domain", return_value={"status": "pending"})
    @patch("products.workflows.backend.facade.api.update_ses_mail_from_subdomain")
    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
    def test_each_sender_keeps_its_own_mail_from_label_while_the_flag_is_off(
        self,
        _name,
        created_label,
        edited_label,
        mock_create_email_domain,
        mock_update_mail_from_subdomain,
        mock_verify_email_domain,
    ):
        self.feature_enabled.side_effect = email_domain_flag(organization_id="another-organization")
        existing = Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="existing@example.com",
            config={
                "email": "existing@example.com",
                "domain": "example.com",
                "mail_from_subdomain": "bounce",
                "provider": "ses",
            },
        )

        new_sender = {"email": "new@example.com", "name": "New", "provider": "ses"}
        if created_label is not None:
            new_sender["mail_from_subdomain"] = created_label

        created = EmailIntegration.create_native_integration(
            new_sender,
            team_id=self.team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )
        EmailIntegration(existing, acting_user=self.user).update_native_integration(
            {"mail_from_subdomain": edited_label}, team_id=self.team.id
        )
        EmailIntegration(created, acting_user=self.user).verify()

        assert mock_create_email_domain.call_args.kwargs["mail_from_subdomain"] == "feedback"
        assert mock_update_mail_from_subdomain.call_args.kwargs["mail_from_subdomain"] == edited_label
        assert mock_verify_email_domain.call_args.kwargs["mail_from_subdomain"] == "feedback"
        assert Integration.objects.get(pk=created.pk).config["mail_from_subdomain"] == "feedback"

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

    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
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

    @patch("products.workflows.backend.facade.api.create_ses_email_domain")
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


class TestEmailIntegrationSESCleanupOnDelete(BaseTest):
    def _create_email_integration(self, email: str, team_id: int, organization_id: str) -> Integration:
        with patch("products.workflows.backend.facade.api.create_ses_email_domain"):
            return EmailIntegration.create_native_integration(
                {"email": email, "name": "Test"},
                team_id=team_id,
                organization_id=organization_id,
                created_by=self.user,
            )

    @patch("posthog.tasks.integrations.delete_ses_identity")
    def test_team_cascade_delete_cleans_up_ses_identity(self, mock_delete_identity):
        team = Team.objects.create(organization=self.organization, name="doomed team")
        self._create_email_integration("owner@partner.com", team.id, str(self.organization.id))

        with self.captureOnCommitCallbacks(execute=True):
            team.delete()

        mock_delete_identity.assert_called_once_with("partner.com")

    @patch("posthog.tasks.integrations.delete_ses_identity")
    def test_cascade_delete_skips_ses_cleanup_while_domain_still_in_use(self, mock_delete_identity):
        team = Team.objects.create(organization=self.organization, name="doomed team")
        self._create_email_integration("owner@partner.com", team.id, str(self.organization.id))
        self._create_email_integration("sibling@partner.com", self.team.id, str(self.organization.id))

        with self.captureOnCommitCallbacks(execute=True):
            team.delete()

        mock_delete_identity.assert_not_called()
