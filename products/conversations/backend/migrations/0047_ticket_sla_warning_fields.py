from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0046_ticket_org_id_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="sla_events_sent",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="ticket",
            name="sla_warning_minutes",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
