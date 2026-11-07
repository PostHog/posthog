from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0081_ticketmacro_shortcut_per_visibility"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="ticket_brief",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
