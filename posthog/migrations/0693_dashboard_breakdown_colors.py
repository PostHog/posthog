# Generated by Django 4.2.18 on 2025-03-21 10:46

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "0692_grouptypemapping_detail_dashboard")]

    operations = [
        migrations.AddField(
            model_name="dashboard",
            name="breakdown_colors",
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
