# Generated by Django 4.2.15 on 2025-01-06 17:07

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0539_user_role_at_organization"),
    ]

    operations = [
        migrations.AddField(
            model_name="featureflag",
            name="is_remote_configuration",
            field=models.BooleanField(default=False),
        ),
    ]
