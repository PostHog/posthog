from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1095_create_group_clickhouse_team"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="ingested_live_event",
            field=models.BooleanField(default=False),
        ),
    ]
