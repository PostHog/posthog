from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field

# The per-model foreign keys TaggedItem carried before the generic pointer replaced them.
LEGACY_FIELDS = [
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
]
LEGACY_COLUMNS = [f"{field}_id" for field in LEGACY_FIELDS]


class Migration(migrations.Migration):
    # DropForeignKey locks every parent before the child and gives up under a budget below
    # deadlock_timeout, so it loses a lock race rather than taking a read down with it. Under
    # atomic = False it lets go of the parents as soon as the drops commit. It reads the names
    # out of pg_constraint, so it does nothing at all once an operator has dropped them.
    atomic = False

    dependencies = [
        ("posthog", "1379_taggeditem_drop_legacy_indexes"),
    ]

    operations = [
        untrack_field(
            "taggeditem",
            *LEGACY_FIELDS,
            database_operations=[DropForeignKey("posthog_taggeditem", column=LEGACY_COLUMNS)],
        ),
    ]
