# Generated migration for schema enforcement_mode field

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0988_ducklakecatalog"),
    ]

    operations = [
        migrations.AddField(
            model_name="eventschema",
            name="enforcement_mode",
            field=models.CharField(
                choices=[("allow", "Allow"), ("reject", "Reject")],
                default="allow",
                max_length=10,
            ),
        ),
    ]
