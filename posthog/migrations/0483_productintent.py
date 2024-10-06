# Generated by Django 4.2.15 on 2024-10-06 16:07

from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0482_alertconfiguration_calculation_interval_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductIntent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("product_type", models.CharField(max_length=255)),
                ("onboarding_completed_at", models.DateTimeField(blank=True, null=True)),
                ("team", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team")),
            ],
            options={
                "unique_together": {("team", "product_type")},
            },
        ),
    ]
