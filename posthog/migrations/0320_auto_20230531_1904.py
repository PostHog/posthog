# Generated by Django 3.2.18 on 2023-05-31 19:04

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0319_user_requested_password_reset_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeatureFlagDashboards",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("dashboard", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.dashboard")),
                (
                    "feature_flag",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.featureflag"),
                ),
            ],
        ),
        migrations.AddField(
            model_name="featureflag",
            name="dashboards",
            field=models.ManyToManyField(
                related_name="dashboards",
                related_query_name="dashboard",
                through="posthog.FeatureFlagDashboards",
                to="posthog.Dashboard",
            ),
        ),
        migrations.AddConstraint(
            model_name="featureflagdashboards",
            constraint=models.UniqueConstraint(
                fields=("feature_flag", "dashboard"), name="unique feature flag for a dashboard"
            ),
        ),
    ]
