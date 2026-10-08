# Project config for django-nextgensquash, the migration squasher. The package
# is a dev-only tool run through `uv run --with`; see the "Squash the Django
# migration history" entry in docs/internal/ci-things-already-tried.md.
NEXTGENSQUASH = {
    # Not in common.migration_utils' managed set either; fold it at the next cutoff.
    "IGNORED_APPS": ["posthog_session"],
    # 0001_initial creates partitioned tables and a view with raw SQL that
    # CreateModel cannot reproduce, and its migrate cost is negligible.
    "FROZEN_APPS": ["warehouse_sources_queue"],
    # Created in the stub: bin/migrate runs migrate_clickhouse in parallel with
    # `manage.py migrate`, and it reads posthog_instancesetting.
    "EARLY_MODELS": {"posthog": ["instancesetting"]},
    # The stub claims posthog's root so check_consistent_history stamps it on
    # live databases (swappable deps resolve to ("posthog", "__first__")).
    "STUB_CLAIMS": {"posthog": [["posthog", "0001_initial_squashed_0284_improved_caching_state_idx"]]},
    # The generated finalize files import these idempotent operations at
    # migrate time, so they stay in this repo instead of the package.
    "OPERATIONS_MODULE": "posthog.migration_helpers.squash_idempotent",
}
