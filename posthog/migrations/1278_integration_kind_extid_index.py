from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction, and PostHog policy keeps
    # concurrent index builds in their own migration away from regular DDL.
    atomic = False
    dependencies = [("posthog", "1277_drop_duckgresserverteam_hot_table_fks")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="integration",
            index=models.Index(fields=["kind", "integration_id"], name="integration_kind_extid"),
        ),
    ]
