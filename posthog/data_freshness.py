"""
Per-project data freshness: is anything at all still reaching this project?

PostHog is multi-modal, so a single "last event" timestamp is a bad proxy for a
project being alive: a project can be busy on session replay and logs while
product analytics has been silent for a month. Every source is therefore probed
separately and the project-level verdict is derived from the union.

Two cost constraints shape the implementation, because this runs on an
interactive path (opening the project switcher):

  1. Every probe either hits Postgres, or hits a ClickHouse table whose sort key
     starts with `team_id` (`app_metrics2`) or is a small per-session rollup
     (`session_replay_events`). Nothing scans the raw events table.
  2. All ClickHouse probes are bounded to `LOOKBACK_DAYS`, so a project with no
     data anywhere costs partition pruning rather than a full history scan.

The bound is why `last_data_at` is nullable per source: `None` means "nothing
within the lookback window", not "never". `Freshness.NEVER` is the only claim
this module makes about all of time, and it leans on `Team.ingested_event`.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Optional

from django.core.cache import cache
from django.db.models import BigIntegerField, Max
from django.db.models.functions import Coalesce

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

logger = structlog.get_logger(__name__)

# How far back the bounded probes look. Anything older reads as "nothing in the window".
LOOKBACK_DAYS = 30
# A source silent for at least this long is quiet. Deliberately shorter than the lookback,
# so there is room between "quiet" and "invisible to us" for the partial verdict to live in.
QUIET_AFTER_DAYS = 7

CACHE_TTL_SECONDS = 10 * 60
DEGRADED_CACHE_TTL_SECONDS = 60


class DataSource(StrEnum):
    """A distinct kind of data a project can receive. Values are part of the API contract."""

    PRODUCT_ANALYTICS = "product_analytics"
    SESSION_REPLAY = "session_replay"
    ERROR_TRACKING = "error_tracking"
    LLM_ANALYTICS = "llm_analytics"
    SURVEYS = "surveys"
    FEATURE_FLAGS = "feature_flags"
    LOGS = "logs"
    APM = "apm"
    DESTINATIONS = "destinations"
    MESSAGING = "messaging"
    DATA_WAREHOUSE = "data_warehouse"


class Freshness(StrEnum):
    """The project-level verdict. Values are part of the API contract.

    Deliberately only three states. The question this answers is "is this project in use",
    which is binary plus the unstarted case. A project still receiving one kind of data is in
    use even if another kind stopped, so per-source decay does not get its own verdict; the
    `sources` breakdown is there for anyone who wants to see why.
    """

    # Never ingested anything, ever. An unstarted project, not a stale one.
    NEVER = "never"
    # Something of any kind arrived recently.
    LIVE = "live"
    # Nothing of any kind arrived recently.
    STALE = "stale"


@dataclass(frozen=True, kw_only=True)
class SourceFreshness:
    data_source: DataSource
    last_data_at: datetime


@dataclass(frozen=True, kw_only=True)
class ProjectFreshness:
    team_id: int
    freshness: Freshness
    last_data_at: Optional[datetime]
    sources: list[SourceFreshness]


# Events that belong to a product other than product analytics. Everything else
# a project sends rolls up into product analytics.
_EVENT_NAME_SOURCES: dict[str, DataSource] = {
    "$exception": DataSource.ERROR_TRACKING,
    "$feature_flag_called": DataSource.FEATURE_FLAGS,
    "survey sent": DataSource.SURVEYS,
    "survey shown": DataSource.SURVEYS,
    "survey dismissed": DataSource.SURVEYS,
}
_LLM_EVENT_PREFIX = "$ai_"

# `app_metrics2.app_source` is already a per-team, per-product activity ledger, so one
# small query covers four products that would otherwise need their own tables.
_APP_METRICS_SOURCES: dict[str, DataSource] = {
    "logs": DataSource.LOGS,
    "traces": DataSource.APM,
    "hog_function": DataSource.DESTINATIONS,
    "hog_flow": DataSource.MESSAGING,
}


def get_organization_data_freshness(organization_id: str, teams: list[Team]) -> list[ProjectFreshness]:
    """Freshness for every passed team, cached per organization.

    Keyed on the team set too, since access control means two members of the same organization
    can see different projects.
    """
    team_ids = sorted(team.id for team in teams)
    fingerprint = hashlib.sha256(",".join(str(team_id) for team_id in team_ids).encode()).hexdigest()[:16]
    cache_key = f"org_data_freshness:{organization_id}:{fingerprint}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result, degraded = _compute(teams)
    # A store being briefly unreachable reads as "no data", which is exactly the wrong answer to
    # pin for a full TTL. Cache it just long enough to absorb a burst of requests.
    cache.set(cache_key, result, DEGRADED_CACHE_TTL_SECONDS if degraded else CACHE_TTL_SECONDS)
    return result


def _compute(teams: list[Team]) -> tuple[list[ProjectFreshness], bool]:
    """Returns the per-team verdicts, and whether any probe failed so the caller can cache accordingly."""
    if not teams:
        return [], False

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    # Ingestion clock skew can stamp data slightly in the future; without a ceiling a single
    # skewed row would pin a dead project to "live" forever.
    horizon = now + timedelta(days=1)

    degraded = False
    by_team: dict[int, dict[DataSource, datetime]] = {team.id: {} for team in teams}
    for probe in (_probe_events, _probe_session_replay, _probe_app_metrics, _probe_data_warehouse):
        try:
            for team_id, source, last_data_at in probe(teams, cutoff, horizon):
                if team_id not in by_team or last_data_at is None:
                    continue
                previous = by_team[team_id].get(source)
                if previous is None or last_data_at > previous:
                    by_team[team_id][source] = last_data_at
        except Exception as e:
            # One unavailable store must not blank out every other source's verdict.
            degraded = True
            logger.warning("data_freshness_probe_failed", probe=probe.__name__, error=str(e))
            capture_exception(e)

    quiet_before = now - timedelta(days=QUIET_AFTER_DAYS)
    return [derive_freshness(team, by_team[team.id], quiet_before) for team in teams], degraded


def derive_freshness(team: Team, found: dict[DataSource, datetime], quiet_before: datetime) -> ProjectFreshness:
    sources = sorted(
        (SourceFreshness(data_source=source, last_data_at=at) for source, at in found.items()),
        key=lambda s: s.last_data_at,
        reverse=True,
    )
    last_data_at = sources[0].last_data_at if sources else None

    if last_data_at is None:
        # `ingested_event` is the only unbounded signal available, so it is what separates a
        # project that never started from one whose data predates the lookback window.
        freshness = Freshness.STALE if team.ingested_event else Freshness.NEVER
    elif last_data_at < quiet_before:
        freshness = Freshness.STALE
    else:
        freshness = Freshness.LIVE

    return ProjectFreshness(
        team_id=team.id,
        freshness=freshness,
        last_data_at=last_data_at,
        sources=sources,
    )


ProbeResult = list[tuple[int, DataSource, Optional[datetime]]]


def _probe_events(teams: list[Team], cutoff: datetime, horizon: datetime) -> ProbeResult:
    """Event-backed products, read from the event definition catalog rather than ClickHouse.

    `posthog_eventdefinition.last_seen_at` is maintained by ingestion and is unbounded in time,
    which makes it both free and more precise than a windowed query. The tradeoff is that it is
    project-scoped, so environments of the same project share a verdict here.
    """
    scopes: dict[int, list[Team]] = {}
    for team in teams:
        scopes.setdefault(team.project_id or team.id, []).append(team)

    definitions = EventDefinition.objects.annotate(
        # Mirrors the table's own `(coalesce(project_id, team_id), name)` uniqueness: one row per
        # project, with `project_id` null on rows that predate projects.
        scope_id=Coalesce("project_id", "team_id", output_field=BigIntegerField())
    ).filter(scope_id__in=scopes.keys(), last_seen_at__isnull=False)
    named = definitions.filter(name__in=_EVENT_NAME_SOURCES.keys())
    prefixed = definitions.filter(name__startswith=_LLM_EVENT_PREFIX)

    results: ProbeResult = []

    def emit(scope_id: int, source: DataSource, last_seen_at: Optional[datetime]) -> None:
        if last_seen_at is None or not (cutoff <= last_seen_at <= horizon):
            return
        for team in scopes.get(scope_id, []):
            results.append((team.id, source, last_seen_at))

    for row in named.values("scope_id", "name").annotate(last_seen=Max("last_seen_at")):
        emit(row["scope_id"], _EVENT_NAME_SOURCES[row["name"]], row["last_seen"])
    for row in prefixed.values("scope_id").annotate(last_seen=Max("last_seen_at")):
        emit(row["scope_id"], DataSource.LLM_ANALYTICS, row["last_seen"])
    # Product analytics is the residual: everything that is not one of the events above.
    residual = definitions.exclude(name__in=_EVENT_NAME_SOURCES.keys()).exclude(name__startswith=_LLM_EVENT_PREFIX)
    for row in residual.values("scope_id").annotate(last_seen=Max("last_seen_at")):
        emit(row["scope_id"], DataSource.PRODUCT_ANALYTICS, row["last_seen"])

    return results


def _probe_session_replay(teams: list[Team], cutoff: datetime, horizon: datetime) -> ProbeResult:
    with tags_context(product=Product.REPLAY, feature=Feature.DATA_FRESHNESS):
        rows = sync_execute(
            """
            SELECT team_id, max(min_first_timestamp)
            FROM session_replay_events
            WHERE team_id IN %(team_ids)s
              AND min_first_timestamp >= %(cutoff)s
              AND min_first_timestamp <= %(horizon)s
            GROUP BY team_id
            """,
            {"team_ids": [team.id for team in teams], "cutoff": cutoff, "horizon": horizon},
        )
    return [(team_id, DataSource.SESSION_REPLAY, _as_utc(last_data_at)) for team_id, last_data_at in rows]


def _probe_app_metrics(teams: list[Team], cutoff: datetime, horizon: datetime) -> ProbeResult:
    with tags_context(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.DATA_FRESHNESS):
        rows = sync_execute(
            """
            SELECT team_id, app_source, max(timestamp)
            FROM app_metrics2
            WHERE team_id IN %(team_ids)s
              AND app_source IN %(app_sources)s
              AND timestamp >= %(cutoff)s
              AND timestamp <= %(horizon)s
            GROUP BY team_id, app_source
            """,
            {
                "team_ids": [team.id for team in teams],
                "app_sources": list(_APP_METRICS_SOURCES.keys()),
                "cutoff": cutoff,
                "horizon": horizon,
            },
        )
    return [
        (team_id, _APP_METRICS_SOURCES[app_source], _as_utc(last_data_at))
        for team_id, app_source, last_data_at in rows
        if app_source in _APP_METRICS_SOURCES
    ]


def _probe_data_warehouse(teams: list[Team], cutoff: datetime, horizon: datetime) -> ProbeResult:
    rows = (
        ExternalDataJob.objects.filter(
            team_id__in=[team.id for team in teams],
            status=ExternalDataJob.Status.COMPLETED,
            finished_at__gte=cutoff,
            finished_at__lte=horizon,
        )
        .values("team_id")
        .annotate(last_synced=Max("finished_at"))
    )
    return [(row["team_id"], DataSource.DATA_WAREHOUSE, row["last_synced"]) for row in rows]


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """ClickHouse hands back naive datetimes; they are always UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)
