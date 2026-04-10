from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0021_slack_config_slack_team_id_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="sla_due_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
