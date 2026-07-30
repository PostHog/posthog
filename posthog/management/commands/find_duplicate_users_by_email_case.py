"""Report — and optionally deactivate — accounts whose emails differ only by case.

Signup was case sensitive until emails were normalized, so some people ended up with two
accounts for the same address (`Foo@bar.com` and `foo@bar.com`). Only one of them wins a
given email lookup, which can leave the owner stuck on an account they never set up.

Usage:
    python manage.py find_duplicate_users_by_email_case
    python manage.py find_duplicate_users_by_email_case --email foo@bar.com
    python manage.py find_duplicate_users_by_email_case --deactivate-abandoned

`--deactivate-abandoned` only touches duplicates that carry nothing at all — no
organization membership, no TOTP device, no passkey, and no successful login ever — and
only when a sibling account survives. Anything else is left for a human: merging two
accounts that both hold data isn't something this command can decide.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, QuerySet
from django.db.models.functions import Lower

import structlog

from posthog.helpers.email_utils import rank_email_case_variants
from posthog.models.user import User

logger = structlog.get_logger(__name__)


def _with_signals(users: QuerySet["User"]) -> QuerySet["User"]:
    """Annotate the signals used both to rank accounts and to judge one abandoned."""
    return users.annotate(
        organization_memberships_count=Count("organization_memberships", distinct=True),
        totp_count=Count("totpdevice", distinct=True),
        passkey_count=Count("webauthn_credentials", distinct=True),
    )


def _is_abandoned(user: User) -> bool:
    return (
        user.organization_memberships_count == 0  # type: ignore[attr-defined]
        and user.totp_count == 0  # type: ignore[attr-defined]
        and user.passkey_count == 0  # type: ignore[attr-defined]
        and user.last_login is None
    )


def _describe(user: User) -> str:
    return (
        f"id={user.id} email={user.email!r} active={user.is_active} "
        f"last_login={user.last_login.isoformat() if user.last_login else 'never'} "
        f"joined={user.date_joined.date().isoformat()} "
        f"orgs={user.organization_memberships_count} "  # type: ignore[attr-defined]
        f"totp={user.totp_count} passkeys={user.passkey_count}"  # type: ignore[attr-defined]
    )


class Command(BaseCommand):
    help = "Find users whose emails differ only by case, and optionally deactivate abandoned duplicates"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--email", help="Only inspect this email address (any casing)")
        parser.add_argument(
            "--deactivate-abandoned",
            action="store_true",
            help="Deactivate duplicates with no organizations, no 2FA and no login, when a sibling survives",
        )
        parser.add_argument("--limit", type=int, help="Stop after this many duplicate email addresses")

    def handle(self, *args: Any, **options: Any) -> None:
        emails = self._duplicate_emails(options.get("email"), options.get("limit"))
        if not emails:
            self.stdout.write("No users with case-variant duplicate emails found.")
            return

        deactivated = 0
        for email in emails:
            ranked = rank_email_case_variants(_with_signals(User.objects.filter(email__iexact=email)), email)
            if len(ranked) < 2:
                continue

            self.stdout.write(f"\n{email}: {len(ranked)} accounts")
            for index, user in enumerate(ranked):
                self.stdout.write(f"  {'keep' if index == 0 else 'dupe'}  {_describe(user)}")

            if options["deactivate_abandoned"]:
                deactivated += self._deactivate_abandoned(ranked)

        self.stdout.write(f"\n{len(emails)} email addresses with case-variant duplicates.")
        if options["deactivate_abandoned"]:
            self.stdout.write(f"Deactivated {deactivated} abandoned duplicate accounts.")

    def _duplicate_emails(self, email: str | None, limit: int | None) -> list[str]:
        if email:
            if User.objects.filter(email__iexact=email).count() < 2:
                raise CommandError(f"{email} does not have case-variant duplicates.")
            return [email.lower()]

        groups = (
            User.objects.annotate(email_lower=Lower("email"))
            .values("email_lower")
            .annotate(account_count=Count("id"))
            .filter(account_count__gt=1)
            .order_by("email_lower")
            .values_list("email_lower", flat=True)
        )
        return list(groups[:limit] if limit else groups)

    def _deactivate_abandoned(self, ranked: list[User]) -> int:
        survivor, duplicates = ranked[0], ranked[1:]
        abandoned = [user for user in duplicates if user.is_active and _is_abandoned(user)]
        if not abandoned:
            self.stdout.write("  nothing safe to deactivate, needs a manual merge")
            return 0

        User.objects.filter(id__in=[user.id for user in abandoned]).update(is_active=False)
        for user in abandoned:
            logger.warning(
                "deactivated_abandoned_email_case_duplicate",
                user_id=user.id,
                survivor_user_id=survivor.id,
            )
            self.stdout.write(f"  deactivated id={user.id} email={user.email!r}")
        return len(abandoned)
