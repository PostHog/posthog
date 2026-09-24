from django.db import migrations

from posthog.migration_helpers import DropIndexConcurrently

# The pre-generic-relation foreign key names. Each carries a partial unique index that kept
# one tag per object; `unique_taggeditem_object_id` and `unique_taggeditem_object_uuid` hold
# that same invariant on the generic pointer, so nothing is unguarded once these are gone.
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
    # DROP INDEX CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1377_untrack_superseded_experiment_settings"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(model_name="taggeditem", name=f"unique_{field}_tagged_item")
                for field in LEGACY_FIELDS
            ],
            # Django declares these as partial UniqueConstraints, which Postgres stores as plain
            # indexes rather than constraints, so they come out concurrently and take no
            # exclusive lock. The helper is idempotent, which is what makes this migration a
            # no-op in a region where an operator already dropped them.
            database_operations=[
                DropIndexConcurrently(
                    index_name=f"unique_{field}_tagged_item",
                    table_name="posthog_taggeditem",
                    columns=f"(tag_id, {field}_id)",
                    unique=True,
                    where=f"{field}_id IS NOT NULL",
                )
                for field in LEGACY_FIELDS
            ],
        ),
    ]
