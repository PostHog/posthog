# Generated by Django 3.1.12 on 2021-09-02 14:08

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0165_dashboarditem_dive_dashboard"),
    ]

    operations = [
        migrations.AddField(
            model_name="plugin",
            name="public_jobs",
            field=models.JSONField(default=dict, null=True),
        ),
    ]
