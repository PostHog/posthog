from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0031_ticket_cc_participants"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="snoozed_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["team", "snoozed_until"], name="posthog_con_team_snooze_idx"),
        ),
    ]
