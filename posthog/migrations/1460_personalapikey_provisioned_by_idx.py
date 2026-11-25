from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1459_validate_personalapikey_provisioned_by_fk"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="personalapikey",
            index=models.Index(
                condition=models.Q(("provisioned_by__isnull", False)),
                fields=["provisioned_by"],
                name="personalapikey_provisioned_by",
            ),
        ),
    ]
