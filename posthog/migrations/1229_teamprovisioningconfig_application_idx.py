from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction. Lives in its own
    # migration per PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False
    dependencies = [("posthog", "1228_teamprovisioningconfig_application")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="teamprovisioningconfig",
            index=models.Index(fields=["application"], name="tpc_application_idx"),
        ),
    ]
