from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0084_teams_channel_sync_denied_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="verified_email",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
    ]
