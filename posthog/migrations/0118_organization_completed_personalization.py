# Generated by Django 3.0.11 on 2021-01-26 12:48

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0117_merge_20210126_0917"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization", name="completed_personalization", field=models.BooleanField(default=False),
        ),
    ]
