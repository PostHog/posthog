from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """The index behind the daily retention prune, built without locking writes out of the table."""

    atomic = False

    dependencies = [
        ("alerts", "0015_insight_alert_investigation"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="insightalertinvestigation",
            index=models.Index(fields=["created_at"], name="insight_alert_inv_age_idx"),
        ),
    ]
