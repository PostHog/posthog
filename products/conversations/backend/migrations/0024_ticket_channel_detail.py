from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0023_ticket_sla_due_at_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="channel_detail",
            field=models.CharField(
                blank=True,
                choices=[
                    ("slack_channel_message", "Channel message"),
                    ("slack_bot_mention", "Bot mention"),
                    ("slack_emoji_reaction", "Emoji reaction"),
                    ("widget_embedded", "Widget"),
                    ("widget_api", "API"),
                ],
                max_length=30,
                null=True,
            ),
        ),
    ]
