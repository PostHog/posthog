from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.conversations.backend.mailgun import MailgunNotConfigured
from products.conversations.backend.models import EmailChannel, EmailChannelKind
from products.conversations.backend.tasks.email import prune_unverified_email_domains

OLD_REGISTRATION = "Mon, 01 Dec 2025 12:00:00 GMT"
NEW_REGISTRATION = "Wed, 14 Jan 2026 12:00:00 GMT"


@time_machine.travel("2026-01-15T12:00:00Z", tick=False)
class TestPruneUnverifiedEmailDomains(BaseTest):
    def _channel(self, domain: str, *, verified: bool = False, age: timedelta = timedelta(days=45)) -> EmailChannel:
        channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.SUPPORT,
            inbound_token=f"token-{EmailChannel.objects.count()}",
            from_email=f"support{EmailChannel.objects.count()}@{domain}",
            from_name="Support",
            domain=domain,
            domain_verified=verified,
        )
        EmailChannel.objects.filter(id=channel.id).update(created_at=timezone.now() - age)
        return channel

    @parameterized.expand(
        [
            ("stale_unverified_channel", [{}], OLD_REGISTRATION, True),
            ("verified_sibling", [{}, {"verified": True}], OLD_REGISTRATION, False),
            ("recent_sibling", [{}, {"age": timedelta(days=2)}], OLD_REGISTRATION, False),
            ("recent_mailgun_registration", [{}], NEW_REGISTRATION, False),
            ("unparseable_mailgun_registration", [{}], "not a date", False),
            ("no_support_channel", [], OLD_REGISTRATION, False),
        ]
    )
    @patch("products.conversations.backend.tasks.email.delete_domain")
    @patch("products.conversations.backend.tasks.email.list_unverified_domains")
    def test_prunes_only_abandoned_support_domains(
        self,
        _name: str,
        channels: list[dict],
        registered_at: str,
        expect_pruned: bool,
        mock_list: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        for options in channels:
            self._channel("example.com", **options)
        mock_list.return_value = [{"name": "example.com", "state": "unverified", "created_at": registered_at}]

        prune_unverified_email_domains()

        assert mock_delete.call_args_list == ([(("example.com",),)] if expect_pruned else [])
        assert EmailChannel.objects.filter(domain="example.com").count() == len(channels)

    @patch("products.conversations.backend.tasks.email.delete_domain")
    @patch("products.conversations.backend.tasks.email.list_unverified_domains")
    def test_one_failed_delete_does_not_stop_the_run(self, mock_list: MagicMock, mock_delete: MagicMock) -> None:
        self._channel("a.example.com")
        self._channel("b.example.com")
        mock_list.return_value = [
            {"name": "a.example.com", "state": "unverified", "created_at": OLD_REGISTRATION},
            {"name": "b.example.com", "state": "unverified", "created_at": OLD_REGISTRATION},
        ]
        mock_delete.side_effect = [RuntimeError("mailgun unavailable"), None]

        prune_unverified_email_domains()

        assert [c.args[0] for c in mock_delete.call_args_list] == ["a.example.com", "b.example.com"]

    @patch("products.conversations.backend.tasks.email.delete_domain")
    @patch("products.conversations.backend.tasks.email.list_unverified_domains", side_effect=MailgunNotConfigured())
    def test_skips_when_mailgun_is_not_configured(self, _mock_list: MagicMock, mock_delete: MagicMock) -> None:
        self._channel("example.com")

        prune_unverified_email_domains()

        mock_delete.assert_not_called()
