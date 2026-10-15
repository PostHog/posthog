from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0076_tag_legacy_conversation_attachments"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="ticket_brief",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
