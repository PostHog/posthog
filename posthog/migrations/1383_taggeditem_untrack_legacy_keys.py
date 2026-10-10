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
    # Each DropForeignKey commits in a transaction of its own, so one drop locks one busy
    # parent and the child rather than all 14 tables at once. A retry skips the keys a
    # failed run already dropped, because DropForeignKey reads what is left from pg_constraint.
    atomic = False

    dependencies = [
        ("posthog", "1382_taggeditem_drop_legacy_constraints"),
    ]

    operations = [
        # The columns stay, so a pod on the old release keeps reading and writing them. Their
        # foreign keys cannot: Django stops cascading into a relation it no longer tracks, and
        # a deferred constraint would then fail every parent delete at COMMIT.
        untrack_field(
            "taggeditem",
            *LEGACY_FIELDS,
            database_operations=[DropForeignKey("posthog_taggeditem", column=f"{field}_id") for field in LEGACY_FIELDS],
        ),
    ]
