import json
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Count

from posthog.models import User
from posthog.session.activity import revoke_other_sessions
from posthog.session.models import Session


class Command(BaseCommand):
    help = (
        "Disable passwords and revoke web sessions for explicitly selected users. "
        "Use --dry-run to preview changes. Does not revoke API/OAuth credentials or send recovery emails."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        targets = parser.add_mutually_exclusive_group(required=True)
        targets.add_argument("--user-uuids", nargs="+", help="User.uuid values, not analytics distinct IDs or emails.")
        targets.add_argument("--user-uuids-file", type=Path, help="File containing one User.uuid per line.")
        parser.add_argument(
            "--operator-uuid", required=True, type=UUID, help="Active staff user performing the operation."
        )
        parser.add_argument(
            "--reason", required=True, help="Audit reference; do not include credentials or customer data."
        )
        parser.add_argument("--dry-run", action="store_true", help="Preview selected users without making changes.")

    def _read_targets(self, values: list[str] | None, path: Path | None) -> set[UUID]:
        if path is not None:
            try:
                values = path.read_text().splitlines()
            except OSError as error:
                raise CommandError(f"Cannot read UUID file: {error}") from error
        try:
            targets = {UUID(value.strip()) for value in values or [] if value.strip()}
        except ValueError as error:
            raise CommandError("Every target must be a user UUID.") from error
        if not targets:
            raise CommandError("At least one user UUID is required.")
        return targets

    def _validate_targets(self, targets: set[UUID], users: list[User], operator: User) -> None:
        missing = targets - {user.uuid for user in users}
        if missing:
            raise CommandError(
                f"Users not found in this region: {', '.join(sorted(map(str, missing)))}. No changes made."
            )
        if operator.uuid in targets:
            raise CommandError("The operator cannot contain their own account. Use another staff operator.")

    def _contain(self, user: User, operator: User, reason: str, region: str) -> int:
        user.set_unusable_password()
        user.save(update_fields=["password"])
        revoked = revoke_other_sessions(user, keep_session_key=None)
        LogEntry.objects.create(
            user_id=operator.pk,
            content_type=ContentType.objects.get_for_model(User),
            object_id=str(user.pk),
            object_repr=str(user.uuid),
            action_flag=CHANGE,
            change_message=json.dumps(
                {
                    "command": "disable_passwords_and_revoke_sessions",
                    "region": region,
                    "reason": reason,
                    "password_disabled": True,
                    "web_sessions_revoked": revoked,
                }
            ),
        )
        return revoked

    def handle(self, *args: Any, **options: Any) -> None:
        region = settings.CLOUD_DEPLOYMENT or "LOCAL"
        reason: str = options["reason"].strip()
        if not reason:
            raise CommandError("A nonempty audit reason is required.")
        targets = self._read_targets(options["user_uuids"], options["user_uuids_file"])
        try:
            operator = User.objects.get(uuid=options["operator_uuid"], is_active=True, is_staff=True)
        except User.DoesNotExist as error:
            raise CommandError("Operator must be an active staff user in this region.") from error

        users = list(User.objects.filter(uuid__in=targets).order_by("pk"))
        self._validate_targets(targets, users, operator)
        session_counts = dict(
            Session.objects.filter(user_id__in=[user.pk for user in users])
            .values("user_id")
            .annotate(count=Count("pk"))
            .values_list("user_id", "count")
        )
        self.stdout.write(f"Region: {region}. Selected accounts: {len(users)}.")
        for user in users:
            self.stdout.write(
                f"uuid={user.uuid} id={user.pk} email={user.email} active={user.is_active} "
                f"usable_password={user.has_usable_password()} web_sessions={session_counts.get(user.pk, 0)}"
            )
        if options["dry_run"]:
            self.stdout.write(
                "DRY RUN: no changes made. Re-run without --dry-run to disable passwords and revoke web sessions."
            )
            return

        with transaction.atomic():
            users = list(User.objects.select_for_update().filter(uuid__in=targets).order_by("pk"))
            self._validate_targets(targets, users, operator)
            revoked_counts = [self._contain(user, operator, reason, region) for user in users]

        for user, revoked in zip(users, revoked_counts):
            self.stdout.write(f"uuid={user.uuid}: password disabled; web_sessions_revoked={revoked}")
        self.stdout.write(
            f"Completed: {len(users)} accounts; {sum(revoked_counts)} web sessions revoked. "
            "Arrange recovery separately. API keys and OAuth credentials were not revoked."
        )
