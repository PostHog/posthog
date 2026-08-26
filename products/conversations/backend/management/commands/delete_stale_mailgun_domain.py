import re
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from products.conversations.backend import mailgun
from products.conversations.backend.models import EmailChannel, EmailChannelKind

# A bare DNS hostname: dot-separated labels of letters, digits, and hyphens, nothing else.
# The argument reaches Mailgun by interpolation into a URL path, and `requests` drops a
# "?"/"#" suffix from that path. Without this guard, an argument like "acme.example.com?x"
# would slip past the channel-in-use check below (which filters on the literal string) yet
# still delete the base domain from Mailgun.
DNS_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


class Command(BaseCommand):
    help = (
        "Release a Mailgun sending domain that no longer has a matching support email channel. "
        "Support remediation for domains orphaned in Mailgun (e.g. the owning project or org was "
        "deleted, or the customer migrated between the US and EU regions). Mailgun refuses to "
        "register a domain another account already holds, so an orphaned registration blocks the "
        "domain from being connected anywhere. "
        "Run this on the region whose CONVERSATIONS_EMAIL_MAILGUN_API_KEY points at the Mailgun "
        "account holding the domain, usually the region the customer migrated away from."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("domain", type=str, help="The sending domain to release from Mailgun")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without deleting anything",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        domain = options["domain"].strip().lower()
        dry_run = options["dry_run"]

        if not DNS_HOSTNAME.fullmatch(domain):
            raise CommandError(
                f"Invalid domain {options['domain']!r}: expected a plain sending domain like acme.example.com"
            )

        # Only support channels own a Mailgun sending-domain registration; customer
        # communication channels just receive captured mail.
        in_use = EmailChannel.objects.filter(domain=domain, kind=EmailChannelKind.SUPPORT)
        if in_use.exists():
            team_ids = sorted(in_use.values_list("team_id", flat=True))
            raise CommandError(
                f"Refusing to delete: domain {domain} is still used by support email channel(s) on team(s) {team_ids}"
            )

        # Look the domain up before deleting so a wrong-region run says so, rather than
        # succeeding silently on Mailgun's 404-is-fine delete.
        try:
            mg_domain = mailgun.get_domain(domain)
        except mailgun.MailgunNotConfigured:
            raise CommandError(
                "This region has no Mailgun API key configured, so it cannot be the region holding "
                f"{domain}. Re-run on the region whose CONVERSATIONS_EMAIL_MAILGUN_API_KEY owns it."
            )

        if mg_domain is None:
            raise CommandError(
                f"Domain {domain} is not registered in this region's Mailgun account. "
                "Re-run on the other region, or the domain is held by a Mailgun account we don't control."
            )

        state = mg_domain.get("state", "unknown")
        self.stdout.write(f"Mailgun has {domain} in state '{state}' with no support channel using it")

        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry run: would delete {domain} from Mailgun"))
            return

        mailgun.delete_domain(domain)
        self.stdout.write(self.style.SUCCESS(f"Released Mailgun domain {domain}"))
