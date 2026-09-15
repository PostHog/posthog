from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("customer_analytics", "0053_ownership_authority"),
    ]

    operations = [
        # Built concurrently so the relationship table stays writable while the index is created. The
        # next migration attaches it as the constraint Django's state declares.
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_relationship_per_source_ref",
                    table_name="customer_analytics_accountrelationship",
                    columns="(team_id, source, source_ref)",
                    unique=True,
                ),
            ],
        ),
    ]
