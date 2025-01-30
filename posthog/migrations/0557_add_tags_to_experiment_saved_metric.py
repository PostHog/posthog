# Generated by Django 4.2.18 on 2025-01-30 00:30

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0556_add_execution_order_to_hog_functions"),
    ]

    operations = [
        migrations.AddField(
            model_name="taggeditem",
            name="experiment_saved_metric",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tagged_items",
                to="posthog.experimentsavedmetric",
            ),
        ),
        migrations.AddConstraint(
            model_name="taggeditem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("experiment_saved_metric__isnull", False)),
                fields=("tag", "experiment_saved_metric"),
                name="unique_experiment_saved_metric_tagged_item",
            ),
        ),
    ]
