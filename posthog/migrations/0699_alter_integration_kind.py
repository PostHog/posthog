from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0698_action_project"),
    ]

    operations = [
        migrations.AlterField(
            model_name="integration",
            name="kind",
            field=models.CharField(
                choices=[
                    ("slack", "Slack"),
                    ("salesforce", "Salesforce"),
                    ("hubspot", "Hubspot"),
                    ("google-pubsub", "Google Pubsub"),
                    ("google-cloud-storage", "Google Cloud Storage"),
                    ("google-ads", "Google Ads"),
                    ("snapchat", "Snapchat"),
                    ("linkedin-ads", "Linkedin Ads"),
                    ("intercom", "Intercom"),
                    ("email", "Email"),
                ],
                max_length=20,
            ),
        ),
    ]
