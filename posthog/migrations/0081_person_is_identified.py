# Generated by Django 3.0.6 on 2020-08-22 18:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0080_update_dashboard_funnel_filters"),
    ]

    operations = [
        migrations.AddField(model_name="person", name="is_identified", field=models.BooleanField(default=False),),
    ]
