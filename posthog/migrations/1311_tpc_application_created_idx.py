from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # required for the concurrent index build

    dependencies = [
        ("posthog", "1310_teamprovisioningconfig_created_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="teamprovisioningconfig",
            index=models.Index(fields=["application", "created_at"], name="tpc_application_created_idx"),
        ),
    ]
