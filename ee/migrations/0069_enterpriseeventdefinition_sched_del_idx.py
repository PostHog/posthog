from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ee", "0068_enterpriseeventdefinition_scheduled_deletion_at"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="enterpriseeventdefinition",
            index=models.Index(
                condition=models.Q(("scheduled_deletion_at__isnull", False)),
                fields=["scheduled_deletion_at"],
                name="ee_eventdef_sched_del_idx",
            ),
        ),
    ]
