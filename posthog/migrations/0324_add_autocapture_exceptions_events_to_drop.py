# Generated by Django 3.2.18 on 2023-06-11 19:10

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0323_alter_batchexportdestination_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="autocapture_exceptions_errors_to_drop",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
