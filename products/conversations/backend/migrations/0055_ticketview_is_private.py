from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("conversations", "0054_ticket_sla_snooze_asc_indexes")]

    operations = [
        migrations.AddField(
            model_name="ticketview",
            name="is_private",
            field=models.BooleanField(default=False),
        ),
    ]
