# Task names pinned by vmalert liveness alerts in PostHog/charts (currently
# FlagsCacheVerificationNotRunning), which fire on
# `increase(posthog_celery_task_success_total{task_name="..."}[window]) == 0`.
#
# Each name here must be passed as `name=` to its @shared_task decorator, so the
# task_name label the alert matches on stays stable across module moves and renames,
# and is pre-created at worker start (posthog/celery.py, _initialize_worker_metrics)
# so a task that stops running freezes at zero instead of vanishing from the metrics.
#
# This module must stay import-light (like posthog/celery_queues.py): the metric seed
# reads it without importing task code, because an import error killing the seed is
# exactly the failure mode the alerts exist to catch.

VERIFY_FLAGS_CACHE_TASK_NAME = "posthog.tasks.hypercache_verification.verify_and_fix_flags_cache_task"
VERIFY_TEAM_METADATA_CACHE_TASK_NAME = "posthog.tasks.hypercache_verification.verify_and_fix_team_metadata_cache_task"
VERIFY_FLAG_DEFINITIONS_CACHE_TASK_NAME = (
    "posthog.tasks.hypercache_verification.verify_and_fix_flag_definitions_cache_task"
)

LIVENESS_ALERTED_TASK_NAMES = (
    VERIFY_FLAGS_CACHE_TASK_NAME,
    VERIFY_TEAM_METADATA_CACHE_TASK_NAME,
    VERIFY_FLAG_DEFINITIONS_CACHE_TASK_NAME,
)
