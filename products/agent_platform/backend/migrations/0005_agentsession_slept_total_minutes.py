# Generated for the session-sleep cumulative cap. See docs/session-sleep.md.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0004_agentsession_sleep_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentsession",
            name="slept_total_minutes",
            field=models.IntegerField(default=0, db_default=0),
        ),
    ]
