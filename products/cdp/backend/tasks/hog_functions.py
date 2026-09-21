from typing import Optional

from django.core.management import call_command
from django.db.models import Count, Q, Value
from django.db.models.fields.json import JSONField
from django.utils import timezone

from celery import shared_task
from prometheus_client import Gauge
from structlog import get_logger

from posthog.celery_queues import CeleryQueue
from posthog.metrics import pushed_metrics_registry
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers
from posthog.redis import get_client
from posthog.scoping_audit import skip_team_scope_audit

from products.actions.backend.models.action import Action

logger = get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
@skip_team_scope_audit
def refresh_affected_hog_functions(
    team_id: Optional[int] = None, action_id: Optional[int] = None, cohort_id: Optional[int] = None
) -> int:
    from products.cdp.backend.models.hog_functions.hog_function import HogFunction

    affected_hog_functions: list[HogFunction] = []

    if action_id:
        action = Action.objects.get(id=action_id)
        team_id = action.team_id
        affected_hog_functions = list(
            HogFunction.objects.select_related("team")
            .filter(team_id=action.team_id)
            .filter(filters__contains={"actions": [{"id": str(action_id)}]})
        )
    elif cohort_id:
        from products.cohorts.backend.models.cohort import Cohort

        try:
            cohort = Cohort.objects.select_related("team").get(id=cohort_id)
        except Cohort.DoesNotExist:
            # Cohort was deleted between signal firing and task execution — nothing to refresh
            return 0
        team = cohort.team

        # Check if this team references the cohort in its test_account_filters
        uses_cohort = any(
            f.get("type") == "cohort" and f.get("value") == cohort.id for f in (team.test_account_filters or [])
        )
        if not uses_cohort:
            return 0

        team_id = team.id

    # For both cohort_id and team_id paths, find hog functions with test account filters enabled
    if team_id and not affected_hog_functions:
        affected_hog_functions = list(
            HogFunction.objects.select_related("team")
            .filter(team_id=team_id)
            .filter(filters__contains={"filter_test_accounts": True})
        )

    if team_id is None:
        raise Exception("Either team_id, action_id, or cohort_id must be provided")

    if not affected_hog_functions:
        return 0

    all_related_actions = (
        Action.objects.select_related("team")
        .filter(team_id=team_id)
        .filter(
            id__in=[
                action_id for hog_function in affected_hog_functions for action_id in hog_function.filter_action_ids
            ]
        )
    )

    actions_by_id = {action.id: action for action in all_related_actions}

    # posthog.cdp.filters pulls hogql.property and with it the HogQL/schema layer;
    # posthog.apps ready() imports this module in every process at setup.
    from posthog.cdp.filters import compile_filters_bytecode  # noqa: PLC0415 — keeps HogQL off the import path

    successfully_compiled_hog_functions = []
    for hog_function in affected_hog_functions:
        compiled_filters = compile_filters_bytecode(hog_function.filters, hog_function.team, actions_by_id)

        # Only update if compilation succeeded (no bytecode_error)
        if not compiled_filters.get("bytecode_error"):
            hog_function.filters = compiled_filters
            hog_function.updated_at = timezone.now()
            successfully_compiled_hog_functions.append(hog_function)
        else:
            logger.warning(
                f"Failed to compile filters for hog function {hog_function.id}: {compiled_filters.get('bytecode_error')}. "
                "Keeping existing filters intact."
            )

    updates = HogFunction.objects.bulk_update(successfully_compiled_hog_functions, ["filters", "updated_at"])

    reload_hog_functions_on_workers(
        team_id=team_id, hog_function_ids=[str(hog_function.id) for hog_function in successfully_compiled_hog_functions]
    )

    return updates


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    max_retries=5,
    default_retry_delay=30,  # retry every 30 seconds
)
def sync_hog_function_templates_task() -> None:
    try:
        logger.info("Running sync_hog_function_templates command (celery task)...")
        call_command("sync_hog_function_templates")
    except Exception as e:
        logger.exception(f"Celery task sync_hog_function_templates failed: {e}")
        raise  # Needed for Celery to trigger a retry


def queue_sync_hog_function_templates() -> None:
    """Queue the sync_hog_function_templates_task with Redis lock to ensure it only runs once."""
    try:
        r = get_client()
        lock_key = "posthog_sync_hog_function_templates_task_lock"
        # setnx returns True if the key was set, False if it already exists
        if r.setnx(lock_key, 1):
            r.expire(lock_key, 60 * 60)  # expire after 1 hour
            logger.info("Queuing sync_hog_function_templates celery task (redis lock)...")
            sync_hog_function_templates_task.delay()
        else:
            logger.info("Not queuing sync_hog_function_templates task: lock already set")
    except Exception as e:
        logger.exception(f"Failed to queue sync_hog_function_templates celery task: {e}")


@skip_team_scope_audit
def uncompilable_filter_counts() -> dict[str, tuple[int, int]]:
    """Per type, how many enabled functions recorded a compile error, split on whether bytecode survived."""
    from products.cdp.backend.models.hog_functions.hog_function import HogFunction

    # `__isnull=True` on a JSON key means the key is absent, which is a different row from one
    # holding a JSON null, so both spellings are matched.
    no_bytecode = Q(filters__bytecode__isnull=True) | Q(filters__bytecode=Value(None, JSONField()))

    rows = (
        HogFunction.objects.filter(deleted=False, enabled=True)
        .exclude(filters__bytecode_error__isnull=True)
        .values("type")
        .annotate(total=Count("id"), dead=Count("id", filter=no_bytecode))
    )
    return {row["type"]: (row["dead"], row["total"] - row["dead"]) for row in rows}


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def count_uncompilable_hog_function_filters() -> None:
    from products.cdp.backend.models.hog_functions.hog_function import HogFunctionType

    counts = uncompilable_filter_counts()

    with pushed_metrics_registry("celery_cdp_uncompilable_hog_function_filters") as registry:
        gauge = Gauge(
            "posthog_cdp_uncompilable_hog_function_filters",
            "Enabled hog functions whose filters recorded a compile error, by whether bytecode survived.",
            labelnames=["type", "state"],
            registry=registry,
        )
        # Every type is written, including the zeros. The push deletes the previous job's metrics,
        # so a type left out would disappear from the series rather than read as none broken.
        for hog_type in HogFunctionType.values:
            dead, kept = counts.get(hog_type, (0, 0))
            gauge.labels(type=hog_type, state="no_bytecode").set(dead)
            gauge.labels(type=hog_type, state="kept_bytecode").set(kept)
