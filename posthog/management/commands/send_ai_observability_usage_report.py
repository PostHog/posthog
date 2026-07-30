from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from posthog.tasks.ai_observability_usage_report import send_ai_observability_usage_reports


class Command(BaseCommand):
    help = "Send the AI observability usage report for a given day"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Print information instead of sending it")
        parser.add_argument("--date", type=str, help="The date to be run in format YYYY-MM-DD")
        parser.add_argument("--async", action="store_true", help="Run the task asynchronously")
        parser.add_argument(
            "--org-ids",
            type=str,
            help="Comma-separated list of organization UUIDs to process (e.g., 'uuid1,uuid2,uuid3')",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        date = options["date"] or timezone.now().date().isoformat()
        run_async = options["async"]
        org_ids_str = options.get("org_ids")

        organization_ids = (
            ([oid.strip() for oid in org_ids_str.split(",") if oid.strip()] or None) if org_ids_str else None
        )

        if run_async:
            send_ai_observability_usage_reports.delay(
                dry_run=dry_run,
                at=date,
                organization_ids=organization_ids,
            )
            print("Queued!")  # noqa: T201
        else:
            send_ai_observability_usage_reports(
                dry_run=dry_run,
                at=date,
                organization_ids=organization_ids,
            )

            if dry_run:
                print("Dry run so not sent.")  # noqa: T201
            elif organization_ids:
                print(f"Done! Processed {len(organization_ids)} organization(s).")  # noqa: T201
            else:
                print("Done!")  # noqa: T201
