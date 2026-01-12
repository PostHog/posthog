from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0969_add_oauth_is_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="failure_type",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
