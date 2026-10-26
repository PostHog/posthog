from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from posthog.models.ssf import SSFConfiguration, SSFConnection, SSFEvent, SSFStream


class Command(BaseCommand):
    help = "Re-encrypt an organization's SSF data with the primary ENCRYPTION_SALT_KEYS key. Keep old keys configured until this completes."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization-id", type=UUID, required=True)
        parser.add_argument(
            "--apply", action="store_true", help="Rewrite encrypted fields. Without this flag, only count rows."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.ENCRYPTION_SALT_KEYS:
            raise CommandError("Configure ENCRYPTION_SALT_KEYS before re-encrypting SSF data.")
        for model, fields in (
            (SSFConfiguration, ["signing_key", "receiver_verification_state"]),
            (SSFConnection, ["remote_token"]),
            (SSFStream, ["subjects", "receiver_token", "verification_state"]),
            (SSFEvent, ["token"]),
        ):
            queryset = model.objects.filter(organization_id=options["organization_id"])
            if options["apply"]:
                count = 0
                for pk in queryset.values_list("pk", flat=True).iterator(chunk_size=500):
                    with transaction.atomic():
                        instance = queryset.select_for_update().filter(pk=pk).first()
                        if instance is not None:
                            instance.save(update_fields=fields)
                            count += 1
            else:
                count = queryset.count()
            self.stdout.write(f"{model._meta.label}: {count} rows {'re-encrypted' if options['apply'] else 'eligible'}")
