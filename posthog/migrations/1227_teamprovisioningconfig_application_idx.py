from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False
    dependencies = [("posthog", "1226_teamprovisioningconfig_application")]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="teamprovisioningconfig",
                    index=models.Index(
                        fields=["application", "stripe_project_id"],
                        name="tpc_app_stripe_proj_idx",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="tpc_app_stripe_proj_idx",
                    table_name="posthog_teamprovisioningconfig",
                    columns="(application_id, stripe_project_id)",
                ),
            ],
        ),
    ]
