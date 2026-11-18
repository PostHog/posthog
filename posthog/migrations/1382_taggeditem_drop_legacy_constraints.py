from django.db import migrations

from posthog.migration_helpers import DropColumnConstraints

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
    # The constraints go before the release that stops filling the legacy keys. That release
    # sets no legacy key, so the check would reject every insert while both releases run.
    # DropColumnConstraints finds them by column, so it also takes the unique indexes earlier
    # constraint swaps left on long-lived databases, and does nothing where the first version
    # of 1376 already dropped them.
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
            database_operations=[
                DropColumnConstraints("posthog_taggeditem", columns=[f"{field}_id" for field in LEGACY_FIELDS]),
            ],
        ),
    ]
