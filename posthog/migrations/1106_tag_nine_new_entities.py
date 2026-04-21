import django.db.models.deletion
from django.db import migrations, models

from posthog.models.utils import build_partial_uniqueness_constraint, build_unique_relationship_check

OLD_RELATED_OBJECTS = (
    "dashboard",
    "insight",
    "event_definition",
    "property_definition",
    "action",
    "feature_flag",
    "experiment_saved_metric",
    "ticket",
)

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

ALL_RELATED_OBJECTS = OLD_RELATED_OBJECTS + NEW_RELATED_OBJECTS

# For each new FK column, record (target_table, target_pk_column, column_type).
# column_type must match the PK type of the target table exactly so the FK
# constraint type-checks. UUIDTModel-based tables use a uuid PK; older models
# inheriting directly from models.Model retain the historical integer PK.
FK_TARGETS: dict[str, tuple[str, str, str]] = {
    "experiment": ("posthog_experiment", "id", "integer"),
    "cohort": ("posthog_cohort", "id", "integer"),
    "notebook": ("posthog_notebook", "id", "uuid"),
    "survey": ("posthog_survey", "id", "uuid"),
    "session_recording_playlist": ("posthog_sessionrecordingplaylist", "id", "integer"),
    "data_warehouse_saved_query": ("posthog_datawarehousesavedquery", "id", "uuid"),
    "hog_function": ("posthog_hogfunction", "id", "uuid"),
    "batch_export": ("posthog_batchexport", "id", "uuid"),
    "error_tracking_issue": ("posthog_errortrackingissue", "id", "uuid"),
}


def _index_name(field: str) -> str:
    return f"posthog_taggeditem_{field}_id_idx"


def _partial_unique_index_name(field: str) -> str:
    return f"unique_{field}_tagged_item"


def _composite_unique_index_name() -> str:
    return "posthog_taggeditem_all_related_object_id_uniq"


def _build_check_sql() -> str:
    clauses = []
    for chosen in ALL_RELATED_OBJECTS:
        parts = []
        for other in ALL_RELATED_OBJECTS:
            if other == chosen:
                parts.append(f'"{other}_id" IS NOT NULL')
            else:
                parts.append(f'"{other}_id" IS NULL')
        clauses.append("(" + " AND ".join(parts) + ")")
    return " OR ".join(clauses)


def _build_composite_columns_sql() -> str:
    return ", ".join(f'"{field}_id"' for field in ALL_RELATED_OBJECTS) + ', "tag_id"'


TARGET_MODEL_LABEL: dict[str, str] = {
    "experiment": "experiments.Experiment",
    "cohort": "Cohort",
    "notebook": "notebooks.Notebook",
    "survey": "surveys.Survey",
    "session_recording_playlist": "SessionRecordingPlaylist",
    "data_warehouse_saved_query": "data_warehouse.DataWarehouseSavedQuery",
    "hog_function": "HogFunction",
    "batch_export": "BatchExport",
    "error_tracking_issue": "error_tracking.ErrorTrackingIssue",
}


def _field_fk(field: str) -> models.ForeignKey:
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.CASCADE,
        related_name="tagged_items",
        to=TARGET_MODEL_LABEL[field],
    )


def _add_column_sql(field: str) -> str:
    target_table, target_pk, column_type = FK_TARGETS[field]
    column = f"{field}_id"
    fk_constraint = f"posthog_taggeditem_{field}_id_fkey"
    return (
        f'ALTER TABLE "posthog_taggeditem" ADD COLUMN IF NOT EXISTS "{column}" '
        f'{column_type} NULL CONSTRAINT "{fk_constraint}" '
        f'REFERENCES "{target_table}"("{target_pk}") DEFERRABLE INITIALLY DEFERRED; '
        f"-- existing-table-constraint-ignore"
    )


def _drop_column_sql(field: str) -> str:
    return f'ALTER TABLE "posthog_taggeditem" DROP COLUMN IF EXISTS "{field}_id";'


class Migration(migrations.Migration):
    atomic = False  # required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("posthog", "1105_alter_oauthapplication_authorization_grant_type"),
        ("experiments", "0009_increase_experiment_description_max_length"),
        ("notebooks", "0003_add_kernel_timeouts"),
        ("surveys", "0001_initial"),
        ("data_warehouse", "0045_alter_externaldatasource_source_type"),
        ("error_tracking", "0014_recommendation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="taggeditem",
                    name="exactly_one_related_object",
                ),
                migrations.AlterUniqueTogether(
                    name="taggeditem",
                    unique_together=set(),
                ),
                *[
                    migrations.AddField(
                        model_name="taggeditem",
                        name=field,
                        field=_field_fk(field),
                    )
                    for field in NEW_RELATED_OBJECTS
                ],
                migrations.AlterUniqueTogether(
                    name="taggeditem",
                    unique_together={("tag", *ALL_RELATED_OBJECTS)},
                ),
                *[
                    migrations.AddConstraint(
                        model_name="taggeditem",
                        constraint=build_partial_uniqueness_constraint(
                            field="tag",
                            related_field=field,
                            constraint_name=_partial_unique_index_name(field),
                        ),
                    )
                    for field in NEW_RELATED_OBJECTS
                ],
                migrations.AddConstraint(
                    model_name="taggeditem",
                    constraint=models.CheckConstraint(
                        check=build_unique_relationship_check(ALL_RELATED_OBJECTS),
                        name="exactly_one_related_object",
                    ),
                ),
            ],
            database_operations=[
                # 1. Drop the old check constraint — it only knows about the
                #    original 8 fields and would reject any row that uses one
                #    of the 9 new FKs.
                migrations.RunSQL(
                    sql='ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object";',
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # 2. Drop the old composite unique constraint/index.
                migrations.RunSQL(
                    sql='ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "posthog_taggeditem_tag_id_dashboard_id_insi_734394e1_uniq";',
                    reverse_sql=migrations.RunSQL.noop,
                ),
                # 3. Add the 9 new nullable FK columns. Nullable adds do not
                #    rewrite the table.
                *[
                    migrations.RunSQL(
                        sql=_add_column_sql(field),
                        reverse_sql=_drop_column_sql(field),
                    )
                    for field in NEW_RELATED_OBJECTS
                ],
                # 4. btree index per FK column, built CONCURRENTLY.
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
                # 5. Partial unique index per new FK column (mirrors the
                #    state-side UniqueConstraint).
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
                # 6. Widened composite unique index over (tag, all FKs). Built
                #    CONCURRENTLY, then promoted to a UNIQUE constraint using
                #    that index so downgrade does not require a re-build.
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
                # 7. New check constraint with NOT VALID so existing rows are
                #    not scanned. Existing rows remain compliant because the
                #    new columns are all NULL for them and the original 8
                #    fields retain their "exactly one is set" invariant.
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "posthog_taggeditem" '
                        'ADD CONSTRAINT "exactly_one_related_object" '
                        f"CHECK (({_build_check_sql()})) NOT VALID; "
                        "-- existing-table-constraint-ignore"
                    ),
                    reverse_sql='ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object";',
                ),
            ],
        )
    ]
