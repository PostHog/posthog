# Generated by Django 4.2.15 on 2024-09-11 22:49

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0469_datawarehousesavedquery_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="WebExperiment",
            fields=[],
            options={
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("posthog.experiment",),
        ),
        migrations.AddField(
            model_name="experiment",
            name="type",
            field=models.CharField(
                blank=True,
                choices=[("web", "web"), ("product", "product")],
                default="product",
                max_length=40,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="experiment",
            name="variants",
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
