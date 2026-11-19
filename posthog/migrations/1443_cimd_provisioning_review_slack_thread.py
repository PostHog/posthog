from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1442_cimd_provisioning_review_partner_message"),
    ]

    operations = [
        migrations.AddField(
            model_name="cimdprovisioningreview",
            name="slack_channel_id",
            field=models.CharField(blank=True, db_default="", default="", max_length=32),
        ),
        migrations.AddField(
            model_name="cimdprovisioningreview",
            name="slack_message_ts",
            field=models.CharField(blank=True, db_default="", default="", max_length=32),
        ),
    ]
