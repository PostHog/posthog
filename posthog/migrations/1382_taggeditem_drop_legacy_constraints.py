from django.db import migrations

from posthog.migration_helpers.lock_phase import lock_tables

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


def lock_taggeditem(apps, schema_editor):
    lock_tables(schema_editor, ["posthog_taggeditem"])


class Migration(migrations.Migration):
    # The constraints go before the release that stops filling the legacy keys. That release
    # sets no legacy key, so the check would reject every insert while both releases run.
    # A database that applied the first version of 1376 already lacks them, so every drop
    # carries IF EXISTS.
    dependencies = [
        ("posthog", "1381_codex_user_integration_unique_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(name="taggeditem", unique_together=set()),
                *[
                    migrations.RemoveConstraint(model_name="taggeditem", name=f"unique_{field}_tagged_item")
                    for field in LEGACY_FIELDS
                ],
                migrations.RemoveConstraint(model_name="taggeditem", name="exactly_one_related_object"),
            ],
            # No reverse: a no-op one would put the constraints back into model state while
            # the database still lacks them.
            database_operations=[
                migrations.RunPython(lock_taggeditem),
                migrations.RunSQL(
                    sql=[
                        *[f'DROP INDEX IF EXISTS "unique_{field}_tagged_item"' for field in LEGACY_FIELDS],
                        'ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS "exactly_one_related_object"',
                        'ALTER TABLE "posthog_taggeditem" DROP CONSTRAINT IF EXISTS '
                        '"posthog_taggeditem_tag_id_dashboard_id_insi_experiment_uniq"',
                    ],
                ),
            ],
        ),
    ]
