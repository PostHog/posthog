# Generated by Django 3.2.12 on 2022-04-28 14:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0229_add_filters_hash_to_dashboard_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboardtile", name="last_refresh", field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dashboardtile", name="refresh_attempt", field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(model_name="dashboardtile", name="refreshing", field=models.BooleanField(null=True),),
    ]
