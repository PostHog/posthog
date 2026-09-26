from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1380_unique_codex_user_integration"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="userintegration",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(kind="codex"),
                        fields=("user",),
                        name="unique_codex_user_integration",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_codex_user_integration",
                    table_name="posthog_user_integration",
                    columns='("user_id")',
                    unique=True,
                    where="WHERE kind = 'codex'",
                ),
            ],
        ),
    ]
