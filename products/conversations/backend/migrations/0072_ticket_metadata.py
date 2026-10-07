from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0071_emailchannel_trusted_relay_sender"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
