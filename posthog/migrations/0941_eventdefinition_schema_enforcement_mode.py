# Generated migration for schema_enforcement_mode field

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0940_user_allow_impersonation"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventdefinition",
            name="schema_enforcement_mode",
            field=models.CharField(
                choices=[("allow", "Allow"), ("reject", "Reject")],
                default="allow",
                max_length=10,
                null=True,
            ),
        ),
    ]
