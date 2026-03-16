from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1048_alter_survey_response_sampling_daily_limits_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="integration",
            name="kind",
            field=models.CharField(
                choices=[
                    ("slack", "Slack"),
                    ("slack-posthog-code", "Slack Posthog Code"),
                    ("salesforce", "Salesforce"),
                    ("hubspot", "Hubspot"),
                    ("google-pubsub", "Google Pubsub"),
                    ("google-cloud-storage", "Google Cloud Storage"),
                    ("google-ads", "Google Ads"),
                    ("google-sheets", "Google Sheets"),
                    ("snapchat", "Snapchat"),
                    ("linkedin-ads", "Linkedin Ads"),
                    ("reddit-ads", "Reddit Ads"),
                    ("tiktok-ads", "Tiktok Ads"),
                    ("bing-ads", "Bing Ads"),
                    ("intercom", "Intercom"),
                    ("email", "Email"),
                    ("linear", "Linear"),
                    ("github", "Github"),
                    ("gitlab", "Gitlab"),
                    ("meta-ads", "Meta Ads"),
                    ("twilio", "Twilio"),
                    ("clickup", "Clickup"),
                    ("vercel", "Vercel"),
                    ("databricks", "Databricks"),
                    ("azure-blob", "Azure Blob"),
                    ("firebase", "Firebase"),
                    ("jira", "Jira"),
                    ("pinterest-ads", "Pinterest Ads"),
                ],
                max_length=20,
            ),
        ),
    ]
