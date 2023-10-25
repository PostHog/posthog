# Generated by Django 3.2.19 on 2023-06-30 16:21

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0333_add_timestamp_fields_to_batch_exports"),
    ]

    operations = [
        migrations.AddField(
            model_name="exportedasset",
            name="expires_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
