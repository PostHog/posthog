from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0078_signingsecret_previous_secret_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="ticket_brief",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
