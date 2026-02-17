# Generated migration for schema enforcement_mode field

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1010_hogflowtemplate_org_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventdefinition",
            name="enforcement_mode",
            field=models.CharField(
                choices=[("allow", "Allow"), ("reject", "Reject")],
                default="allow",
                max_length=10,
            ),
        ),
        AddIndexConcurrently(
            model_name="eventdefinition",
            index=models.Index(
                fields=["team_id"],
                name="posthog_eventdef_enforce_idx",
                condition=models.Q(enforcement_mode="reject"),
            ),
        ),
    ]
