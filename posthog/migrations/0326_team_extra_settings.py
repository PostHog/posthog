# Generated by Django 3.2.18 on 2023-06-13 13:29

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0325_alter_dashboardtemplate_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="extra_settings",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
