# Index backing the cross-team due-source scan in the refresh coordinator.
# Concurrent build avoids locking the sources table; isolated in its own
# migration so a failed build doesn't block the rest of the schema change.

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0005_bk_doc_tombstoned_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="knowledgesource",
                    index=models.Index(
                        fields=["refresh_interval", "last_refresh_at"],
                        name="bk_source_refresh_due",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="bk_source_refresh_due",
                    table_name="posthog_business_knowledge_knowledgesource",
                    columns="(refresh_interval, last_refresh_at)",
                ),
            ],
        ),
    ]
