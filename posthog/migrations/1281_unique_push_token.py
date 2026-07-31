from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1280_transfer_push_token_ownership")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="userpushtoken",
                    name="token",
                    field=models.TextField(
                        unique=True,
                        help_text="Opaque push token issued by the platform push service (e.g. Expo push token).",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_user_push_token_token_uniq",
                    table_name="posthog_user_push_token",
                    columns="(token)",
                    unique=True,
                ),
            ],
        ),
    ]
