# Generated by Django 3.2.12 on 2022-05-26 16:21

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0236_add_instance_setting_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationinvite", name="message", field=models.TextField(blank=True, null=True),
        ),
    ]
