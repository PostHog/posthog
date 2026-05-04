from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1140_integrationrepositorycacheentry"),
    ]

    operations = [
        migrations.AlterField(
            model_name="integration",
            name="kind",
            field=models.CharField(
                choices=[
                    ("apns", "Apple Push"),
                    ("azure-blob", "Azure Blob"),
                    ("bing-ads", "Bing Ads"),
                    ("clickup", "Clickup"),
                    ("customerio-app", "Customerio App"),
                    ("customerio-track", "Customerio Track"),
                    ("customerio-webhook", "Customerio Webhook"),
                    ("databricks", "Databricks"),
                    ("email", "Email"),
                    ("firebase", "Firebase"),
                    ("github", "Github"),
                    ("gitlab", "Gitlab"),
                    ("google-ads", "Google Ads"),
                    ("google-cloud-service-account", "Google Cloud Service Account"),
                    ("google-cloud-storage", "Google Cloud Storage"),
                    ("google-pubsub", "Google Pubsub"),
                    ("google-sheets", "Google Sheets"),
                    ("hubspot", "Hubspot"),
                    ("instagram", "Instagram"),
                    ("intercom", "Intercom"),
                    ("jira", "Jira"),
                    ("linear", "Linear"),
                    ("linkedin-ads", "Linkedin Ads"),
                    ("meta-ads", "Meta Ads"),
                    ("pinterest-ads", "Pinterest Ads"),
                    ("postgresql", "Postgresql"),
                    ("reddit-ads", "Reddit Ads"),
                    ("salesforce", "Salesforce"),
                    ("slack", "Slack"),
                    ("slack-posthog-code", "Slack Posthog Code"),
                    ("snapchat", "Snapchat"),
                    ("stripe", "Stripe"),
                    ("tiktok-ads", "Tiktok Ads"),
                    ("twilio", "Twilio"),
                    ("vercel", "Vercel"),
                ],
                max_length=32,
            ),
        ),
    ]
