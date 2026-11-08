from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1416_organization_soft_delete"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="organization",
            index=models.Index(
                condition=models.Q(("deleted", True)),
                fields=["id"],
                name="org_deleted_id_idx",
            ),
        ),
    ]
