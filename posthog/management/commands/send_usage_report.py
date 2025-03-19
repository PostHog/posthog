from django.core.management.base import BaseCommand

from posthog.tasks.usage_report import send_all_org_usage_reports


class Command(BaseCommand):
    help = "Send the usage report for a given day"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", type=bool, help="Print information instead of sending it")
        parser.add_argument("--date", type=str, help="The date to be ran in format YYYY-MM-DD")
        parser.add_argument(
            "--skip-capture-event",
            type=str,
            help="Skip the posthog capture events - for retrying to billing service",
        )
        parser.add_argument("--async", type=bool, help="Run the task asynchronously")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        date = options["date"]
        skip_capture_event = options["skip_capture_event"]
        run_async = options["async"]

        if run_async:
            send_all_org_usage_reports.delay(
                dry_run=dry_run,
                at=date,
                skip_capture_event=skip_capture_event,
            )
        else:
            send_all_org_usage_reports(
                dry_run=dry_run,
                at=date,
                skip_capture_event=skip_capture_event,
            )

            if dry_run:
                print("Dry run so not sent.")  # noqa T201
        print("Done!")  # noqa T201
