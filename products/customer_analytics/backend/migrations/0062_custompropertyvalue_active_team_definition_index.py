from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("customer_analytics", "0061_announcement_send_as"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="custompropertyvalue",
            index=models.Index(
                condition=models.Q(("is_deleted", False)),
                fields=["team", "definition", "account"],
                name="cpv_active_team_definition_idx",
            ),
        ),
    ]
