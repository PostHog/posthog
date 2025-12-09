# Generated migration for adding unread message counters to Ticket model

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0003_add_session_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="unread_customer_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="ticket",
            name="unread_team_count",
            field=models.IntegerField(default=0),
        ),
    ]
