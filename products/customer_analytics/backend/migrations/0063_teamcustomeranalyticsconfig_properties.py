from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("customer_analytics", "0062_custompropertyvalue_active_team_definition_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="teamcustomeranalyticsconfig",
            name="properties",
            field=models.JSONField(db_default={}, default=dict),
        ),
    ]
