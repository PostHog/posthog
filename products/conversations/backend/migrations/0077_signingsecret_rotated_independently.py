from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0076_tag_legacy_conversation_attachments"),
    ]

    operations = [
        migrations.AddField(
            model_name="signingsecret",
            name="rotated_independently",
            field=models.BooleanField(default=False),
        ),
    ]
