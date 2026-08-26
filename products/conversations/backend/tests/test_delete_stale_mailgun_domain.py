import uuid

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from products.conversations.backend.mailgun import MailgunNotConfigured
from products.conversations.backend.models import EmailChannel, EmailChannelKind

COMMAND = "delete_stale_mailgun_domain"
MAILGUN = "products.conversations.backend.management.commands.delete_stale_mailgun_domain.mailgun"


class TestDeleteStaleMailgunDomain(BaseTest):
    def _create_support_channel(self, domain: str = "acme.example.com") -> EmailChannel:
        return EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.SUPPORT,
            inbound_token=uuid.uuid4().hex,
            from_email=f"support@{domain}",
            from_name="Acme Support",
            domain=domain,
        )

    def test_refuses_while_a_support_channel_still_uses_the_domain(self):
        self._create_support_channel()

        with patch(MAILGUN) as mock_mailgun:
            with pytest.raises(CommandError, match=f"team\\(s\\) \\[{self.team.id}\\]"):
                call_command(COMMAND, "acme.example.com")

        mock_mailgun.delete_domain.assert_not_called()

    @parameterized.expand(
        [
            ("query_suffix", "acme.example.com?x"),
            ("fragment_suffix", "acme.example.com#x"),
            ("path_suffix", "acme.example.com/domains"),
        ]
    )
    def test_rejects_a_domain_argument_with_url_control_characters(self, _name, domain):
        # A support channel on the base domain the mangled argument would otherwise slip past.
        self._create_support_channel()

        with patch(MAILGUN) as mock_mailgun:
            with pytest.raises(CommandError, match="Invalid domain"):
                call_command(COMMAND, domain)

        mock_mailgun.get_domain.assert_not_called()
        mock_mailgun.delete_domain.assert_not_called()

    def test_releases_an_orphaned_domain(self):
        with patch(MAILGUN) as mock_mailgun:
            mock_mailgun.get_domain.return_value = {"state": "active"}
            call_command(COMMAND, "ACME.example.com")

        mock_mailgun.delete_domain.assert_called_once_with("acme.example.com")

    def test_dry_run_reports_without_deleting(self):
        with patch(MAILGUN) as mock_mailgun:
            mock_mailgun.get_domain.return_value = {"state": "active"}
            call_command(COMMAND, "acme.example.com", "--dry-run")

        mock_mailgun.delete_domain.assert_not_called()

    def test_wrong_region_is_reported_instead_of_silently_succeeding(self):
        with patch(MAILGUN) as mock_mailgun:
            mock_mailgun.get_domain.return_value = None
            with pytest.raises(CommandError, match="not registered in this region"):
                call_command(COMMAND, "acme.example.com")

        mock_mailgun.delete_domain.assert_not_called()

    def test_region_without_an_api_key_is_reported(self):
        with patch(MAILGUN) as mock_mailgun:
            mock_mailgun.MailgunNotConfigured = MailgunNotConfigured
            mock_mailgun.get_domain.side_effect = MailgunNotConfigured("no key")
            with pytest.raises(CommandError, match="no Mailgun API key"):
                call_command(COMMAND, "acme.example.com")

        mock_mailgun.delete_domain.assert_not_called()
