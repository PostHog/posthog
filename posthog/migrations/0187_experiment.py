# Generated by Django 3.2.5 on 2021-12-06 13:48

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0186_insight_refresh_attempt"),
    ]

    operations = [
        migrations.CreateModel(
            name="Experiment",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, max_length=400, null=True)),
                ("description", models.CharField(blank=True, max_length=400, null=True)),
                ("filters", models.JSONField(default=dict)),
                ("parameters", models.JSONField(default=dict, null=True)),
                ("start_date", models.DateTimeField()),
                ("end_date", models.DateTimeField(null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
                (
                    "feature_flag",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.featureflag"),
                ),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
        ),
    ]
