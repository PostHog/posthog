# Generated migration for schema enforcement_mode field

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1001_fix_person_property_in_operator"),
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
        migrations.AddIndex(
            model_name="eventdefinition",
            index=models.Index(
                fields=["enforcement_mode"],
                name="posthog_eventdef_enforce_idx",
                condition=models.Q(enforcement_mode="reject"),
            ),
        ),
    ]
