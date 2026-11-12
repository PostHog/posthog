from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1433_integrationrepositorycacheentry_activity"),
    ]

    operations = [
        migrations.AddField(
            model_name="identityproviderconfig",
            name="scim_token_digest",
            field=models.CharField(blank=True, max_length=128, null=True, unique=True),
        ),
    ]
