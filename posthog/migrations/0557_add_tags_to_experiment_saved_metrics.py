# Generated by Django 4.2.18 on 2025-01-30 12:23

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0556_add_execution_order_to_hog_functions"),
    ]

    operations = [
        # This is a workaround to fix the unique_together constraint on TaggedItem
        # Django thinks there's a unique_together constraint on TaggedItem, but there isn't
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterUniqueTogether(
                    name="taggeditem",
                    unique_together=set(),
                ),
            ],
        ),
        migrations.RemoveConstraint(
            model_name="taggeditem",
            name="exactly_one_related_object",
        ),
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
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(
                        ("dashboard__isnull", False),
                        ("insight__isnull", True),
                        ("event_definition__isnull", True),
                        ("property_definition__isnull", True),
                        ("action__isnull", True),
                        ("feature_flag__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                    ),
                    models.Q(
                        ("dashboard__isnull", True),
                        ("insight__isnull", False),
                        ("event_definition__isnull", True),
                        ("property_definition__isnull", True),
                        ("action__isnull", True),
                        ("feature_flag__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                    ),
                    models.Q(
                        ("dashboard__isnull", True),
                        ("insight__isnull", True),
                        ("event_definition__isnull", False),
                        ("property_definition__isnull", True),
                        ("action__isnull", True),
                        ("feature_flag__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                    ),
                    models.Q(
                        ("dashboard__isnull", True),
                        ("insight__isnull", True),
                        ("event_definition__isnull", True),
                        ("property_definition__isnull", False),
                        ("action__isnull", True),
                        ("feature_flag__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                    ),
                    models.Q(
                        ("dashboard__isnull", True),
                        ("insight__isnull", True),
                        ("event_definition__isnull", True),
                        ("property_definition__isnull", True),
                        ("action__isnull", False),
                        ("feature_flag__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                    ),
                    models.Q(
                        ("dashboard__isnull", True),
                        ("insight__isnull", True),
                        ("event_definition__isnull", True),
                        ("property_definition__isnull", True),
                        ("action__isnull", True),
                        ("feature_flag__isnull", False),
                        ("experiment_saved_metric__isnull", True),
                    ),
                    models.Q(
                        ("dashboard__isnull", True),
                        ("insight__isnull", True),
                        ("event_definition__isnull", True),
                        ("property_definition__isnull", True),
                        ("action__isnull", True),
                        ("feature_flag__isnull", True),
                        ("experiment_saved_metric__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="exactly_one_related_object",
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
