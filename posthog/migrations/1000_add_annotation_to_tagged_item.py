import django.db.models.deletion
from django.db import migrations, models

from posthog.models.utils import build_partial_uniqueness_constraint, build_unique_relationship_check

RELATED_OBJECTS_OLD = (
    "dashboard",
    "insight",
    "event_definition",
    "property_definition",
    "action",
    "feature_flag",
    "experiment_saved_metric",
    "ticket",
)

RELATED_OBJECTS_NEW = (*RELATED_OBJECTS_OLD, "annotation")


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0999_remove_presorted_events_modifier"),
    ]

    operations = [
        # Add annotation FK
        migrations.AddField(
            model_name="taggeditem",
            name="annotation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tagged_items",
                to="posthog.annotation",
            ),
        ),
        # Remove old check constraint
        migrations.RemoveConstraint(
            model_name="taggeditem",
            name="exactly_one_related_object",
        ),
        # Remove old partial uniqueness constraints
        *[
            migrations.RemoveConstraint(
                model_name="taggeditem",
                name=f"unique_{field}_tagged_item",
            )
            for field in RELATED_OBJECTS_OLD
        ],
        # Remove old unique_together
        migrations.AlterUniqueTogether(
            name="taggeditem",
            unique_together=set(),
        ),
        # Add new unique_together including annotation
        migrations.AlterUniqueTogether(
            name="taggeditem",
            unique_together={("tag", *RELATED_OBJECTS_NEW)},
        ),
        # Add new partial uniqueness constraints
        *[
            migrations.AddConstraint(
                model_name="taggeditem",
                constraint=build_partial_uniqueness_constraint(
                    field="tag", related_field=field, constraint_name=f"unique_{field}_tagged_item"
                ),
            )
            for field in RELATED_OBJECTS_NEW
        ],
        # Add new check constraint
        migrations.AddConstraint(
            model_name="taggeditem",
            constraint=models.CheckConstraint(
                check=build_unique_relationship_check(RELATED_OBJECTS_NEW),
                name="exactly_one_related_object",
            ),
        ),
    ]
