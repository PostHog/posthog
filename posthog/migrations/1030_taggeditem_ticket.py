import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1029_hogflow_draft_fields"),
        ("conversations", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="taggeditem",
            name="ticket",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tagged_items",
                to="conversations.ticket",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="taggeditem",
            unique_together={
                (
                    "tag",
                    "dashboard",
                    "insight",
                    "event_definition",
                    "property_definition",
                    "action",
                    "feature_flag",
                    "experiment_saved_metric",
                    "ticket",
                )
            },
        ),
        migrations.RemoveConstraint(
            model_name="taggeditem",
            name="exactly_one_related_object",
        ),
        migrations.AddConstraint(
            model_name="taggeditem",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(
                        ("action__isnull", False),
                        ("dashboard__isnull", True),
                        ("event_definition__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                        ("feature_flag__isnull", True),
                        ("insight__isnull", True),
                        ("property_definition__isnull", True),
                        ("ticket__isnull", True),
                    ),
                    models.Q(
                        ("action__isnull", True),
                        ("dashboard__isnull", False),
                        ("event_definition__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                        ("feature_flag__isnull", True),
                        ("insight__isnull", True),
                        ("property_definition__isnull", True),
                        ("ticket__isnull", True),
                    ),
                    models.Q(
                        ("action__isnull", True),
                        ("dashboard__isnull", True),
                        ("event_definition__isnull", False),
                        ("experiment_saved_metric__isnull", True),
                        ("feature_flag__isnull", True),
                        ("insight__isnull", True),
                        ("property_definition__isnull", True),
                        ("ticket__isnull", True),
                    ),
                    models.Q(
                        ("action__isnull", True),
                        ("dashboard__isnull", True),
                        ("event_definition__isnull", True),
                        ("experiment_saved_metric__isnull", False),
                        ("feature_flag__isnull", True),
                        ("insight__isnull", True),
                        ("property_definition__isnull", True),
                        ("ticket__isnull", True),
                    ),
                    models.Q(
                        ("action__isnull", True),
                        ("dashboard__isnull", True),
                        ("event_definition__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                        ("feature_flag__isnull", False),
                        ("insight__isnull", True),
                        ("property_definition__isnull", True),
                        ("ticket__isnull", True),
                    ),
                    models.Q(
                        ("action__isnull", True),
                        ("dashboard__isnull", True),
                        ("event_definition__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                        ("feature_flag__isnull", True),
                        ("insight__isnull", False),
                        ("property_definition__isnull", True),
                        ("ticket__isnull", True),
                    ),
                    models.Q(
                        ("action__isnull", True),
                        ("dashboard__isnull", True),
                        ("event_definition__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                        ("feature_flag__isnull", True),
                        ("insight__isnull", True),
                        ("property_definition__isnull", False),
                        ("ticket__isnull", True),
                    ),
                    models.Q(
                        ("action__isnull", True),
                        ("dashboard__isnull", True),
                        ("event_definition__isnull", True),
                        ("experiment_saved_metric__isnull", True),
                        ("feature_flag__isnull", True),
                        ("insight__isnull", True),
                        ("property_definition__isnull", True),
                        ("ticket__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="exactly_one_related_object",
            ),
        ),
        migrations.AddConstraint(
            model_name="taggeditem",
            constraint=models.UniqueConstraint(
                condition=models.Q(("ticket__isnull", False)),
                fields=("tag", "ticket"),
                name="unique_ticket_tagged_item",
            ),
        ),
    ]
