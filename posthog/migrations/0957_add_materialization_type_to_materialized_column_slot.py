from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0956_team_conversations_enabled_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="materializedcolumnslot",
            name="materialization_type",
            field=models.CharField(
                max_length=10,
                choices=[
                    ("dmat", "Dynamic Materialized Column"),
                    ("eav", "EAV Table"),
                ],
                default="dmat",
            ),
        ),
    ]
