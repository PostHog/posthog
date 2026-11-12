from datetime import timedelta
from email.utils import format_datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config

from products.conversations.backend.models import EmailChannel, EmailChannelKind, MailgunDomainRegistration
from products.conversations.backend.services.mailgun_domain_cleanup import cleanup_mailgun_domains

SERVICE = "products.conversations.backend.services.mailgun_domain_cleanup"
DAYS_60 = timedelta(days=60)
DAYS_365 = timedelta(days=365)


def _mailgun_domain(name: str, state: str, age: timedelta = timedelta(days=60)) -> dict[str, Any]:
    return {"name": name, "state": state, "created_at": format_datetime(timezone.now() - age, usegmt=True)}


class TestMailgunDomainCleanup(BaseTest):
    def _channel(self, domain: str, *, verified: bool, age: timedelta) -> None:
        channel = EmailChannel.objects.create(
            team=self.team,
            kind=EmailChannelKind.SUPPORT,
            inbound_token=f"token-{domain}-{verified}",
            from_email=f"support-{int(verified)}@{domain}",
            from_name="Support",
            domain=domain,
            domain_verified=verified,
        )
        EmailChannel.objects.filter(id=channel.id).update(created_at=timezone.now() - age)

    @parameterized.expand(
        [
            ("registered_unverified_orphan", [], DAYS_60, "unverified", DAYS_60, False, True),
            ("orphan_registered_by_another_region", [], None, "unverified", DAYS_60, False, False),
            ("orphan_reclaimed_by_another_region", [], DAYS_60, "unverified", timedelta(days=2), False, False),
            ("orphan_just_registered", [], timedelta(minutes=5), "unverified", timedelta(minutes=5), False, False),
            ("active_orphan", [], DAYS_60, "active", DAYS_60, False, False),
            ("inbound_domain", [], DAYS_60, "unverified", DAYS_60, True, False),
            ("old_unverified_channel", [(False, DAYS_365)], DAYS_365, "unverified", DAYS_365, False, False),
            ("verified_channel", [(True, DAYS_60)], DAYS_60, "active", DAYS_60, False, False),
        ]
    )
    def test_deletes_only_unverified_domains_this_region_registered_with_no_support_channel(
        self,
        _name: str,
        channels: list[tuple[bool, timedelta]],
        registration_age: timedelta | None,
        mailgun_state: str,
        mailgun_age: timedelta,
        is_inbound_domain: bool,
        should_delete: bool,
    ) -> None:
        domain = "acme.example.com"
        for verified, age in channels:
            self._channel(domain, verified=verified, age=age)
        if registration_age is not None:
            MailgunDomainRegistration.objects.create(domain=domain, registered_at=timezone.now() - registration_age)

        with (
            override_instance_config("CONVERSATIONS_EMAIL_INBOUND_DOMAIN", domain if is_inbound_domain else ""),
            patch(f"{SERVICE}.list_domains", return_value=[_mailgun_domain(domain, mailgun_state, mailgun_age)]),
            patch(f"{SERVICE}.delete_domain") as delete_domain,
            patch(f"{SERVICE}.DELETE_PAUSE_SECONDS", 0),
        ):
            cleanup_mailgun_domains(dry_run=False)

        assert [c.args[0] for c in delete_domain.call_args_list] == ([domain] if should_delete else [])
