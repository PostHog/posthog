from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1383_taggeditem_untrack_legacy_keys"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="userintegration",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(kind="claude"),
                        fields=("user",),
                        name="unique_claude_user_integration",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_claude_user_integration",
                    table_name="posthog_user_integration",
                    columns='("user_id")',
                    unique=True,
                    where="WHERE kind = 'claude'",
                ),
            ],
        ),
    ]
