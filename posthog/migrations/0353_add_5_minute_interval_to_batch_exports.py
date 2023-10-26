# Generated by Django 3.2.19 on 2023-10-06 11:07

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0352_auto_20230926_1833"),
    ]

    operations = [
        migrations.AlterField(
            model_name="batchexport",
            name="interval",
            field=models.CharField(
                choices=[
                    ("hour", "hour"),
                    ("day", "day"),
                    ("week", "week"),
                    ("every 5 minutes", "every 5 minutes"),
                ],
                default="hour",
                help_text="The interval at which to export data.",
                max_length=64,
            ),
        ),
    ]
