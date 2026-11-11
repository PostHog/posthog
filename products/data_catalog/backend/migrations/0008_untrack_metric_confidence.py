from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("data_catalog", "0007_alter_metric_team_and_more"),
    ]

    operations = [
        # The column stays so pods on the previous release keep naming it; a later migration drops it.
        untrack_field("metric", "confidence"),
    ]
