from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0015_ticket_slack_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="slack_team_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
