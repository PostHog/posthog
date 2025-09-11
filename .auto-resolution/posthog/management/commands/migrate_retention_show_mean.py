from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.models import Insight


def migrate_show_mean_from_boolean_to_string(batch_size: int, live_run: bool = False) -> None:
    """
    Migrate the showMean boolean field to meanRetentionCalculation string field in retention insights.
    """
    retention_insights = Insight.objects_including_soft_deleted.filter(
        query__source__kind="RetentionQuery",
        query__source__retentionFilter__has_key="showMean",
    )

    total_count = retention_insights.count()
    processed_count = 0

    print(f"Found {total_count} retention insights to migrate")  # noqa: T201

    for insight in retention_insights.iterator(chunk_size=batch_size):
        show_mean_value = insight.query["source"]["retentionFilter"]["showMean"]
        if isinstance(show_mean_value, bool):
            if live_run:
                with transaction.atomic():
                    # Convert boolean to string - if True, use 'simple' else 'none'
                    insight.query["source"]["retentionFilter"]["meanRetentionCalculation"] = (
                        "simple" if show_mean_value else "none"
                    )
                    insight.save()
                processed_count += 1
                if processed_count % batch_size == 0:
                    print(f"Processed {processed_count}/{total_count} insights")  # noqa: T201
            else:
                processed_count += 1
                if processed_count % batch_size == 0:
                    print(f"[DRY RUN] Would process {processed_count}/{total_count} insights")  # noqa: T201

    status = "" if live_run else "[DRY RUN] Would have "
    print(f"\n{status}Processed {processed_count} retention insights in total")  # noqa: T201


class Command(BaseCommand):
    help = "Migrate retention insights showMean boolean field to meanRetentionCalculation string field"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of insights to process in each batch (default: 100)",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually execute the migration (default is dry-run)",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        live_run = options["live_run"]

        if not live_run:
            print("Running in dry-run mode. Use --live-run to apply changes")  # noqa: T201

        migrate_show_mean_from_boolean_to_string(batch_size=batch_size, live_run=live_run)
