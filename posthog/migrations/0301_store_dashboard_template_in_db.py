# Generated by Django 3.2.16 on 2023-02-21 12:56

import django.contrib.postgres.fields
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0300_add_constraints_to_person_override"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboardtemplate",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="dashboardtemplate",
            name="created_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
            ),
        ),
        migrations.AddField(
            model_name="dashboardtemplate",
            name="deleted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="dashboardtemplate",
            name="image_url",
            field=models.CharField(blank=True, max_length=8201, null=True),
        ),
        migrations.AddField(
            model_name="dashboardtemplate",
            name="variables",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="dashboardtemplate",
            name="dashboard_description",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
        migrations.AlterField(
            model_name="dashboardtemplate",
            name="dashboard_filters",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="dashboardtemplate",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255), blank=True, default=list, size=None
            ),
        ),
    ]
