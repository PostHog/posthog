from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("posthog", "1416_sharing_configuration_publishers")]
    operations = [
        SafeAddIndexConcurrently(
            model_name="sharingconfiguration",
            index=models.Index(fields=["shared_by"], name="sharingconfig_shared_by_idx"),
        ),
    ]
