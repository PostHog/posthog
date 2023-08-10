# Generated by Django 3.2.18 on 2023-06-29 12:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0339_add_user_scene_personalisation"),
    ]

    operations = [
        migrations.AddField(
            model_name="action",
            name="bytecode",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="action",
            name="bytecode_error",
            field=models.TextField(blank=True, null=True),
        ),
    ]
