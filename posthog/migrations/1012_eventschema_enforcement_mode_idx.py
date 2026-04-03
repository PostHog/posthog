# Generated migration for schema enforcement_mode index

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1011_eventschema_enforcement_mode"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                fields=["team_id"],
                name="posthog_eventdef_enforce_idx",
                condition=models.Q(enforcement_mode="reject"),
            ),
        ),
    ]
