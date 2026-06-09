"""
Detection of whether a team has begun ingesting real production traffic.

This is the activation milestone behind `Team.ingested_production_event`. The
file is split into two layers so the heuristic can be retuned without
touching the rest of the system:

  1. CRITERION  — `_teams_meeting_criterion(team_ids)` is the single source
                  of truth for what counts as "production traffic." Edit the
                  constants below or the SQL inside that function to retune.
                  The contract is intentionally narrow: `Iterable[team_id]
                  -> set[team_id]`. The implementation is free to change.

  2. TRANSITION — `_mark_teams_ingested_production_event(team_ids, now)` is
                  the only code that marks the column and emits the
                  `first team production event ingested` analytics event.
                  Idempotent under concurrent runs via `SELECT FOR UPDATE
                  SKIP LOCKED`.

Scheduling lives in `products/growth/dags/team_production_event_activation.py`,
which wires these helpers into a Dagster job + daily schedule.

To recalibrate, edit the constants below (and/or the SQL in
`_teams_meeting_criterion`). Run the new criterion against a recent
ClickHouse sample first to estimate how many teams qualify; the metric needs
to remain interpretable.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Final

from django.db import transaction

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.ph_client import ph_scoped_capture

# --- Heuristic parameters ---------------------------------------------------
# Tune these to recalibrate the metric.

DISTINCT_USERS_THRESHOLD: Final[int] = 15
WINDOW_DAYS: Final[int] = 30
SWEEP_BATCH_SIZE: Final[int] = 5_000


# --- Criterion --------------------------------------------------------------


def _teams_meeting_criterion(team_ids: Iterable[int]) -> set[int]:
    """Return the subset of `team_ids` whose recent traffic meets the criterion.

    Single source of truth for "what counts as production traffic." The
    contract is intentionally narrow so callers don't need to know what the
    bar is — they just ask which of these teams qualify.
    """
    team_id_list = list(team_ids)
    if not team_id_list:
        return set()

    # Internal background job, not a customer-facing query — tag it so it's
    # attributed correctly in ClickHouse query analytics (and so it doesn't trip
    # the untagged-query guard that raises in local dev).
    with tags_context(product=Product.INTERNAL, feature=Feature.ENRICHMENT):
        rows = sync_execute(
            """
            SELECT team_id
            FROM events
            WHERE team_id IN %(team_ids)s
              AND timestamp >= now() - toIntervalDay(%(window_days)s)
            GROUP BY team_id
            HAVING uniq(distinct_id) >= %(threshold)s
            """,
            {
                "team_ids": team_id_list,
                "window_days": WINDOW_DAYS,
                "threshold": DISTINCT_USERS_THRESHOLD,
            },
        )
    return {row[0] for row in rows}


# --- Transition -------------------------------------------------------------


def _mark_teams_ingested_production_event(team_ids: Iterable[int], now: datetime) -> int:
    """Mark `ingested_production_event` for the given teams and emit one
    activation event per team that is newly marked.

    Concurrent-safe via `SELECT FOR UPDATE SKIP LOCKED`: a second run
    running in parallel sees only the rows the first run hasn't locked, so
    each team's event fires at most once. Returns the number of teams that
    were marked this call.
    """
    target_ids = list(team_ids)
    if not target_ids:
        return 0

    with transaction.atomic():
        teams_to_mark = list(
            Team.objects.select_for_update(skip_locked=True)
            .filter(id__in=target_ids, ingested_production_event=False)
            .only("id", "uuid")
        )
        if not teams_to_mark:
            return 0
        Team.objects.filter(id__in=[t.id for t in teams_to_mark]).update(
            ingested_production_event=True,
            ingested_production_event_last_checked_at=now,
        )

    # Emit outside the transaction so the PostHog client round-trip doesn't
    # hold row locks. Lost events on worker exit are guarded by
    # `ph_scoped_capture`'s explicit flush.
    with ph_scoped_capture() as capture:
        for team in teams_to_mark:
            capture(
                distinct_id=str(team.uuid),
                event="first team production event ingested",
                properties={
                    "distinct_users_threshold": DISTINCT_USERS_THRESHOLD,
                    "window_days": WINDOW_DAYS,
                },
                groups=groups(team=team),
            )
    return len(teams_to_mark)


# --- Per-batch helper used by the Dagster job ------------------------------


def evaluate_and_mark_team_batch(team_ids: Iterable[int], now: datetime) -> tuple[int, int]:
    """Evaluate one batch of unflagged team IDs and apply the result.

    Returns `(qualifying_count, marked_count)`. `marked_count <=
    qualifying_count` because a concurrent run may have already marked
    rows under `SELECT FOR UPDATE SKIP LOCKED`.
    """
    batch = list(team_ids)
    if not batch:
        return 0, 0

    qualifying_ids = _teams_meeting_criterion(batch)
    marked = _mark_teams_ingested_production_event(qualifying_ids, now=now) if qualifying_ids else 0

    # Bump `_last_checked_at` for the rest so we know we evaluated them.
    # Qualifying teams already had `_last_checked_at` set inside the
    # transition helper, so don't double-write them here.
    non_qualifying = [tid for tid in batch if tid not in qualifying_ids]
    if non_qualifying:
        Team.objects.filter(id__in=non_qualifying).update(
            ingested_production_event_last_checked_at=now,
        )

    return len(qualifying_ids), marked
