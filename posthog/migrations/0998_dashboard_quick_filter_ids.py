# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0997_oauthapplication_auth_brand"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="quick_filter_ids",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
