from django.conf import settings
from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0023_migrate_data_modeling_models"),
        ("posthog", "1193_oauthaccesstoken_label_oauthapplication_scopes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="datamodelingjob",
                    index=models.Index(fields=["team", "status"], name="datamodelingjob_team_status"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="datamodelingjob_team_status",
                    table_name="posthog_datamodelingjob",
                    columns="(team_id, status)",
                ),
            ],
        ),
    ]
