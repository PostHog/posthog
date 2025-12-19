# Generated migration for schema_enforcement_mode field

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0950_add_exception_type_to_exported_asset"),
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
