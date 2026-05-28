from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # `AddIndexConcurrently` requires atomic=False. Lives in its own migration per
    # PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False
    dependencies = [("posthog", "1187_teamprovisioningconfig_application")]

    operations = [
        AddIndexConcurrently(
            model_name="teamprovisioningconfig",
            index=models.Index(
                fields=["application", "stripe_project_id"],
                name="tpc_app_stripe_proj_idx",
            ),
        ),
    ]
