# Generated by Django 4.2.15 on 2024-12-23 09:00

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0535_alter_hogfunction_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="skip_weekend",
            field=models.BooleanField(default=False),
        ),
    ]
