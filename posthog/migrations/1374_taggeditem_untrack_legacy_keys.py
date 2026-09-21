from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field

# The per-model foreign keys TaggedItem carried before the generic pointer replaced them.
LEGACY_FIELDS = (
    "dashboard",
    "insight",
    "event_definition",
    "property_definition",
    "action",
    "feature_flag",
    "experiment_saved_metric",
    "ticket",
    "account",
    "endpoint",
    "replay_scanner",
    "project",
    "experiment",
)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1373_taggeditem_generic_pointer_unique"),
    ]

    operations = [
        # The constraints go first. A row written by the next release sets no legacy key, so
        # the check would reject every insert while the two releases run side by side.
        migrations.AlterUniqueTogether(name="taggeditem", unique_together=set()),
        *[
            migrations.RemoveConstraint(model_name="taggeditem", name=f"unique_{field}_tagged_item")
            for field in LEGACY_FIELDS
        ],
        migrations.RemoveConstraint(model_name="taggeditem", name="exactly_one_related_object"),
        # The columns stay, so a pod on the old release keeps reading and writing them. Their
        # foreign keys cannot: Django stops cascading into a relation it no longer tracks, and
        # a deferred constraint would then fail every parent delete at COMMIT.
        untrack_field(
            "taggeditem",
            *LEGACY_FIELDS,
            database_operations=[DropForeignKey("posthog_taggeditem", column=f"{field}_id") for field in LEGACY_FIELDS],
        ),
    ]
