# Generated by Django 3.2.18 on 2023-05-09 18:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0313_early_access_feature"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="extra_settings",
            field=models.JSONField(default={}),
        ),
    ]
