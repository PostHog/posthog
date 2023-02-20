# Generated by Django 3.2.16 on 2023-02-20 13:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0302_alter_dashboardtemplate_dashboard_description"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dashboardtemplate",
            name="dashboard_filters",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="dashboardtemplate",
            name="variables",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
