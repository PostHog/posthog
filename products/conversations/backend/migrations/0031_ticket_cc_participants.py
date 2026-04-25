from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0030_ticketview"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="cc_participants",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
