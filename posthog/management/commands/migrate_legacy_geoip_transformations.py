import time

from django.core.management.base import BaseCommand

import structlog

from posthog.cdp.validation import compile_hog

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)

LEGACY_TEMPLATE_ID = "plugin-posthog-plugin-geoip"
NEW_TEMPLATE_ID = "template-geoip"
BATCH_SIZE = 1000


class Command(BaseCommand):
    help = "Migrate legacy plugin-posthog-plugin-geoip transformations in place to template-geoip"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without making changes",
        )
        parser.add_argument("--team-ids", type=str, help="Comma separated list of team ids to migrate")
        parser.add_argument("--limit", type=int, default=None, help="Max number of transformations to migrate")

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        team_ids = options.get("team_ids")
        limit = options.get("limit")
        start_time = time.time()

        template = HogFunctionTemplate.get_template(NEW_TEMPLATE_ID)
        if not template:
            self.stdout.write(self.style.ERROR(f"Template {NEW_TEMPLATE_ID} not found in the database, aborting"))
            return

        # All migrated rows get the same code, so compile once upfront
        bytecode = compile_hog(template.code, "transformation")

        queryset = HogFunction.objects.filter(
            type="transformation",
            template_id=LEGACY_TEMPLATE_ID,
            deleted=False,
        ).order_by("id")

        if team_ids:
            queryset = queryset.filter(team_id__in=[int(team_id) for team_id in team_ids.split(",")])

        if limit is not None:
            queryset = queryset[:limit]

        # Snapshot the ids upfront: migrating a row removes it from the queryset's filter
        # match set, so paginating the live queryset with OFFSET would skip rows
        ids = list(queryset.values_list("id", flat=True))
        total_found = len(ids)
        migrated_count = 0
        failed: list[tuple[str, int, str]] = []

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - No changes will be made"))

        self.stdout.write(f"Found {total_found} legacy GeoIP transformations to migrate")

        for batch_start in range(0, total_found, BATCH_SIZE):
            batch_ids = ids[batch_start : batch_start + BATCH_SIZE]

            self.stdout.write(f"Processing batch of {len(batch_ids)} transformations...")

            for hog_function in HogFunction.objects.filter(id__in=batch_ids).order_by("id"):
                if dry_run:
                    migrated_count += 1
                    self.stdout.write(
                        f"  Would migrate id={hog_function.id} team={hog_function.team_id} "
                        f"enabled={hog_function.enabled} name={hog_function.name!r}"
                    )
                    continue

                # One broken row must not abort the whole run
                try:
                    hog_function.template_id = NEW_TEMPLATE_ID
                    hog_function.hog = template.code
                    hog_function.bytecode = bytecode
                    hog_function.hog_function_template = template
                    hog_function.icon_url = template.icon_url
                    hog_function.save(
                        update_fields=[
                            "template_id",
                            "hog",
                            "bytecode",
                            "hog_function_template",
                            "icon_url",
                            "updated_at",
                        ]
                    )
                    migrated_count += 1
                except Exception as e:
                    failed.append((str(hog_function.id), hog_function.team_id, str(e)))

        duration = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Migration completed in {duration:.2f}s. "
                f"Found: {total_found}, Migrated: {migrated_count}, Failed: {len(failed)}"
            )
        )

        if failed:
            self.stdout.write(self.style.WARNING(f"{len(failed)} transformation(s) failed and were skipped:"))
            for fn_id, team_id, error in failed:
                self.stdout.write(f"  id={fn_id} team={team_id} error={error}")
