from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0024_email_config_and_message_mapping"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="email_subject",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name="ticket",
            name="email_from",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
    ]
