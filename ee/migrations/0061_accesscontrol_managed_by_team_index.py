from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for concurrent index creation

    dependencies = [
        ("ee", "0060_accesscontrol_managed_at_accesscontrol_managed_by_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="accesscontrol",
            index=models.Index(
                condition=models.Q(("managed_by__isnull", False)),
                fields=["team"],
                name="access_control_managed_by_team",
            ),
        ),
    ]
