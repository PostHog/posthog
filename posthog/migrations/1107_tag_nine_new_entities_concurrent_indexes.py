from django.db import migrations

NEW_RELATED_OBJECTS = (
    "experiment",
    "cohort",
    "notebook",
    "survey",
    "session_recording_playlist",
    "data_warehouse_saved_query",
    "hog_function",
    "batch_export",
    "error_tracking_issue",
)

ALL_RELATED_OBJECTS = (
    "dashboard",
    "insight",
    "event_definition",
    "property_definition",
    "action",
    "feature_flag",
    "experiment_saved_metric",
    "ticket",
    *NEW_RELATED_OBJECTS,
)


def _index_name(field: str) -> str:
    return f"posthog_taggeditem_{field}_id_idx"


def _partial_unique_index_name(field: str) -> str:
    return f"unique_{field}_tagged_item"


def _composite_unique_index_name() -> str:
    return "posthog_taggeditem_all_related_object_id_uniq"


def _build_composite_columns_sql() -> str:
    return ", ".join(f'"{field}_id"' for field in ALL_RELATED_OBJECTS) + ', "tag_id"'


class Migration(migrations.Migration):
    # CONCURRENTLY cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1106_tag_nine_new_entities"),
    ]

    # State is already up-to-date from 1106 — we only mutate the database
    # side here. Every statement is idempotent via IF NOT EXISTS so retries
    # after a mid-flight failure are safe.
    operations = [
        # btree index per new FK column.
        *[
            migrations.RunSQL(
                sql=(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                    f'"{_index_name(field)}" ON "posthog_taggeditem" ("{field}_id");'
                ),
                reverse_sql=f'DROP INDEX CONCURRENTLY IF EXISTS "{_index_name(field)}";',
            )
            for field in NEW_RELATED_OBJECTS
        ],
        # Partial unique index per new FK column — mirrors the state-side
        # UniqueConstraint added in 1106.
        *[
            migrations.RunSQL(
                sql=(
                    f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                    f'"{_partial_unique_index_name(field)}" '
                    f'ON "posthog_taggeditem" ("tag_id", "{field}_id") '
                    f'WHERE "{field}_id" IS NOT NULL; '
                    f"-- not-null-ignore"
                ),
                reverse_sql=(
                    f"DROP INDEX CONCURRENTLY IF EXISTS "
                    f'"{_partial_unique_index_name(field)}";'
                ),
            )
            for field in NEW_RELATED_OBJECTS
        ],
        # Widened composite unique index over (tag, all FKs). Built
        # CONCURRENTLY, then promoted to a UNIQUE constraint using that
        # index so we avoid a second table scan.
        migrations.RunSQL(
            sql=(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                f'"{_composite_unique_index_name()}" '
                f'ON "posthog_taggeditem" ({_build_composite_columns_sql()});'
            ),
            reverse_sql=(
                f"DROP INDEX CONCURRENTLY IF EXISTS "
                f'"{_composite_unique_index_name()}";'
            ),
        ),
        migrations.RunSQL(
            sql=(
                f'ALTER TABLE "posthog_taggeditem" '
                f'ADD CONSTRAINT "{_composite_unique_index_name()}" '
                f'UNIQUE USING INDEX "{_composite_unique_index_name()}"; '
                f"-- existing-table-constraint-ignore"
            ),
            reverse_sql=(
                f'ALTER TABLE "posthog_taggeditem" '
                f'DROP CONSTRAINT IF EXISTS "{_composite_unique_index_name()}";'
            ),
        ),
    ]
