from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1234_oauthapplication_optional_scopes_and_more")]

    operations = [
        migrations.AlterField(
            model_name="userintegration",
            name="kind",
            field=models.CharField(
                choices=[("github", "Github"), ("slack", "Slack")],
                max_length=32,
            ),
        ),
    ]
