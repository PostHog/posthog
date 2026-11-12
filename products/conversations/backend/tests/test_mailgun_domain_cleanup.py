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
DOMAIN = "acme.example.com"
DAYS_60 = timedelta(days=60)
DAYS_365 = timedelta(days=365)


def _mailgun_domain(name: str, state: str, age: timedelta = DAYS_60, mailgun_domain_id: str = "mg-1") -> dict[str, Any]:
    return {
        "id": mailgun_domain_id,
        "name": name,
        "state": state,
        "created_at": format_datetime(timezone.now() - age, usegmt=True),
    }


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

    def _register(self, domain: str, mailgun_domain_id: str = "mg-1", age: timedelta = DAYS_60) -> None:
        MailgunDomainRegistration.objects.create(
            domain=domain, mailgun_domain_id=mailgun_domain_id, registered_at=timezone.now() - age
        )

    def _run(
        self,
        listed: list[dict[str, Any]],
        current: dict[str, dict[str, Any] | None] | None = None,
        inbound_domain: str = "",
    ) -> list[str]:
        by_name = {item["name"]: item for item in listed} if current is None else current
        with (
            override_instance_config("CONVERSATIONS_EMAIL_INBOUND_DOMAIN", inbound_domain),
            patch(f"{SERVICE}.list_domains", return_value=listed),
            patch(f"{SERVICE}.get_domain", side_effect=lambda name: by_name.get(name)),
            patch(f"{SERVICE}.delete_domain") as delete_domain,
            patch(f"{SERVICE}.DELETE_PAUSE_SECONDS", 0),
        ):
            cleanup_mailgun_domains(dry_run=False)
        return [c.args[0] for c in delete_domain.call_args_list]

    @parameterized.expand(
        [
            ("registered_unverified_orphan", [], "mg-1", "unverified", DAYS_60, False, True),
            ("orphan_registered_by_another_region", [], None, "unverified", DAYS_60, False, False),
            ("orphan_reclaimed_by_another_region", [], "mg-0", "unverified", DAYS_60, False, False),
            ("orphan_just_registered", [], "mg-1", "unverified", timedelta(minutes=5), False, False),
            ("active_orphan", [], "mg-1", "active", DAYS_60, False, False),
            ("inbound_domain", [], "mg-1", "unverified", DAYS_60, True, False),
            ("old_unverified_channel", [(False, DAYS_365)], "mg-1", "unverified", DAYS_365, False, False),
            ("verified_channel", [(True, DAYS_60)], "mg-1", "active", DAYS_60, False, False),
        ]
    )
    def test_deletes_only_unverified_domains_this_region_registered_with_no_support_channel(
        self,
        _name: str,
        channels: list[tuple[bool, timedelta]],
        registered_id: str | None,
        mailgun_state: str,
        mailgun_age: timedelta,
        is_inbound_domain: bool,
        should_delete: bool,
    ) -> None:
        for verified, age in channels:
            self._channel(DOMAIN, verified=verified, age=age)
        if registered_id is not None:
            self._register(DOMAIN, registered_id)

        deleted = self._run(
            [_mailgun_domain(DOMAIN, mailgun_state, mailgun_age)],
            inbound_domain=DOMAIN if is_inbound_domain else "",
        )

        assert deleted == ([DOMAIN] if should_delete else [])

    @parameterized.expand(
        [
            ("reclaimed_by_another_region", _mailgun_domain(DOMAIN, "unverified", mailgun_domain_id="mg-2")),
            ("verified_since_listing", _mailgun_domain(DOMAIN, "active")),
            ("removed_since_listing", None),
        ]
    )
    def test_skips_delete_when_registration_changed_after_listing(
        self, _name: str, current: dict[str, Any] | None
    ) -> None:
        self._register(DOMAIN)

        deleted = self._run([_mailgun_domain(DOMAIN, "unverified")], current={DOMAIN: current})

        assert deleted == []

    @parameterized.expand(
        [
            ("missing_from_listing_but_still_registered", None, _mailgun_domain(DOMAIN, "active"), True),
            ("removed_from_mailgun", None, None, False),
            (
                "reclaimed_by_another_region",
                _mailgun_domain(DOMAIN, "active", mailgun_domain_id="mg-2"),
                _mailgun_domain(DOMAIN, "active", mailgun_domain_id="mg-2"),
                False,
            ),
        ]
    )
    def test_prunes_registration_only_after_mailgun_confirms_it_is_gone(
        self, _name: str, listed: dict[str, Any] | None, current: dict[str, Any] | None, should_keep: bool
    ) -> None:
        self._register(DOMAIN)

        self._run([listed] if listed else [], current={DOMAIN: current})

        assert MailgunDomainRegistration.objects.filter(domain=DOMAIN).exists() == should_keep

    @parameterized.expand(
        [
            ("registered_with_first_channel", DAYS_60 + timedelta(minutes=1), True),
            ("reclaimed_after_first_channel", timedelta(days=2), False),
            ("registered_long_before_first_channel", DAYS_365, False),
        ]
    )
    def test_backfilled_registration_adopts_only_a_mailgun_registration_made_with_its_first_channel(
        self, _name: str, mailgun_age: timedelta, should_adopt: bool
    ) -> None:
        self._register(DOMAIN, mailgun_domain_id="", age=DAYS_60)

        deleted = self._run([_mailgun_domain(DOMAIN, "unverified", mailgun_age)])

        assert deleted == ([DOMAIN] if should_adopt else [])
        assert MailgunDomainRegistration.objects.get(domain=DOMAIN).mailgun_domain_id == (
            "mg-1" if should_adopt else ""
        )
