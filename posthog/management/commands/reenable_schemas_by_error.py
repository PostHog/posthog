from django.core.management.base import BaseCommand

import structlog

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema, update_should_sync

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Re-enable schemas that were auto-disabled by a specific non-retryable error substring"

    def add_arguments(self, parser):
        parser.add_argument(
            "error",
            type=str,
            help="Error substring to match against latest_error (case-insensitive)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List affected schemas without re-enabling them",
        )
        parser.add_argument(
            "--source-type",
            type=str,
            default=None,
            help="Optionally filter by source type (e.g. Postgres, MySQL)",
        )

    def handle(self, *args, **options):
        error_substring = options["error"]
        dry_run = options["dry_run"]
        source_type = options["source_type"]

        schemas = (
            ExternalDataSchema.objects.select_related("source")
            .filter(
                should_sync=False,
                deleted=False,
                latest_error__icontains=error_substring,
            )
            .exclude(latest_error__isnull=True)
        )

        if source_type:
            schemas = schemas.filter(source__source_type=source_type)

        schemas = list(schemas)

        if not schemas:
            self.stdout.write(self.style.WARNING(f"No disabled schemas found matching error: {error_substring}"))
            return

        self.stdout.write(f"Found {len(schemas)} disabled schema(s) matching '{error_substring}':\n")

        for schema in schemas:
            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} source={schema.source_id} "
                f"name={schema.name} source_type={schema.source.source_type}"
            )

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\nDry run — {len(schemas)} schema(s) would be re-enabled."))
            return

        succeeded = 0
        failed = 0

        for schema in schemas:
            try:
                update_should_sync(schema_id=str(schema.id), team_id=schema.team_id, should_sync=True)
                succeeded += 1
                logger.info(
                    "Re-enabled schema",
                    schema_id=str(schema.id),
                    team_id=schema.team_id,
                    source_type=schema.source.source_type,
                )
            except Exception:
                failed += 1
                logger.exception("Failed to re-enable schema", schema_id=str(schema.id), team_id=schema.team_id)

        self.stdout.write(self.style.SUCCESS(f"\nDone. Re-enabled: {succeeded}, Failed: {failed}"))
