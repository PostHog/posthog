from django.db import migrations
from django.db.models import Count, Max

import structlog

logger = structlog.get_logger(__name__)


def clean_duplicates(apps, schema_editor):
    """Delete duplicate InsightViewed records where team and user are NULL."""
    InsightViewed = apps.get_model("posthog", "InsightViewed")

    # Find insights with duplicate NULL team/user records
    duplicates = (
        InsightViewed.objects.filter(team__isnull=True, user__isnull=True)
        .values("insight_id")
        .annotate(count=Count("id"), keep_id=Max("id"))
        .filter(count__gt=1)
    )

    deleted_count = 0
    for dup in duplicates:
        # Delete all but the most recent (highest id) for each insight
        result = (
            InsightViewed.objects.filter(
                team__isnull=True,
                user__isnull=True,
                insight_id=dup["insight_id"],
            )
            .exclude(id=dup["keep_id"])
            .delete()
        )
        deleted_count += result[0]

    logger.info("clean_duplicates_complete", deleted_count=deleted_count)


class Migration(migrations.Migration):
    # atomic=True (default) - cleanup runs in a transaction for safety

    dependencies = [
        ("posthog", "0945_scheduledchange_recurring_fields"),
    ]

    operations = [
        # Clean up existing duplicates before the next migration adds the unique index
        migrations.RunPython(clean_duplicates, migrations.RunPython.noop),
    ]
