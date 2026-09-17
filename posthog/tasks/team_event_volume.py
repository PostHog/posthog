from time import perf_counter

from django.utils import timezone

import structlog
from celery import shared_task

from posthog.api_queries_budget import budget_enabled
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import CH_TRANSIENT_ERRORS
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema
from posthog.models.team import Team
from posthog.models.team.team_event_volume import TeamEventVolume
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)

EVENT_VOLUME_DAYS = 365


@shared_task(
    ignore_result=True, autoretry_for=CH_TRANSIENT_ERRORS, retry_backoff=60, retry_backoff_max=600, max_retries=3
)
@skip_team_scope_audit
def update_team_event_volumes() -> None:
    if not budget_enabled():
        return
    started = perf_counter()
    computed_at = timezone.now()
    tag_queries(product=Product.INTERNAL, feature=Feature.API_QUERIES_BUDGET)
    rows = sync_execute(
        f"""
        SELECT team_id, count() AS events
        FROM {events_read_table(use_new_events_schema())}
        WHERE timestamp >= now() - INTERVAL %(days)s DAY
        GROUP BY team_id
        """,
        {"days": EVENT_VOLUME_DAYS},
        workload=Workload.OFFLINE,
    )
    team_ids = set(Team.objects.values_list("id", flat=True))
    volumes = [
        TeamEventVolume(team_id=team_id, events_last_year=events, computed_at=computed_at)
        for team_id, events in rows
        if team_id in team_ids
    ]
    TeamEventVolume.objects.bulk_create(
        volumes,
        update_conflicts=True,
        update_fields=["events_last_year", "computed_at"],
        unique_fields=["team"],
        batch_size=1000,
    )
    # A team with no events in the window is absent from the result, so its row is the only one
    # this run did not stamp.
    reset = TeamEventVolume.objects.filter(computed_at__lt=computed_at).update(
        events_last_year=0, computed_at=computed_at
    )
    logger.info(
        "team_event_volumes_updated", teams=len(volumes), reset=reset, seconds=round(perf_counter() - started, 1)
    )
