"""
Per-project data freshness: is anything at all still reaching this project?

PostHog is multi-modal, so a single "last event" timestamp is a bad proxy for a
project being alive: a project can be busy on session replay and logs while
product analytics has been silent for a month. Every source is therefore probed
separately and the project-level verdict is derived from the union.

Two cost constraints shape the implementation, because this runs on an
interactive path (opening the project switcher):

  1. Probes are grouped by datastore rather than by product, so eleven sources
     cost four queries. Each one reads a small per-team table or an index that
     leads with the team: `app_metrics2` sorts on `team_id` first, the event
     catalog has a `(coalesce(project_id, team_id), name)` unique index, and
     `external_data_schema` holds one row per schema. Nothing scans raw events.
     `session_replay_events` is the exception, sorting on
     `(toDate(min_first_timestamp), team_id, session_id)`, so its cost scales
     with the window as well as the team count.
  2. Every probe is bounded to `LOOKBACK_DAYS`, so a project with no data
     anywhere costs partition pruning rather than a full history scan.

The bound is why `last_data_at` is nullable per project: `None` means "nothing
within the lookback window", not "never". `Freshness.NEVER` is the only claim
this module makes about all of time, and it leans on `Team.ingested_event`.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Optional

from django.db.models import BigIntegerField, Case, CharField, Max, Value, When
from django.db.models.functions import Coalesce

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.utils import get_safe_cache, safe_cache_set

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.surveys.backend.util import SurveyEventName
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

logger = structlog.get_logger(__name__)

# How far back the bounded probes look. Anything older reads as "nothing in the window".
LOOKBACK_DAYS = 30
# A project silent for at least this long is stale. Shorter than the lookback, so a stale
# project can still report roughly how long it has been quiet rather than only that it is.
QUIET_AFTER_DAYS = 7

CACHE_TTL_SECONDS = 10 * 60
DEGRADED_CACHE_TTL_SECONDS = 60
# Cached values are pickled dataclass instances, so a shape change has to miss rather than
# unpickle into the new class missing a field. Bump when ProjectFreshness/SourceFreshness change.
_CACHE_SCHEMA_VERSION = 1


class DataSource(StrEnum):
    """A distinct kind of data a project can receive. Values are part of the API contract.

    Spelled to match `ProductKey` so this doesn't become a second product vocabulary.
    """

    PRODUCT_ANALYTICS = "product_analytics"
    SESSION_REPLAY = "session_replay"
    ERROR_TRACKING = "error_tracking"
    LLM_ANALYTICS = "llm_analytics"
    SURVEYS = "surveys"
    FEATURE_FLAGS = "feature_flags"
    LOGS = "logs"
    TRACING = "tracing"
    PIPELINE_DESTINATIONS = "pipeline_destinations"
    WORKFLOWS = "workflows"
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


# One (team_id, source, timestamp) row per thing a probe found. Probes never emit a null
# timestamp or a team they weren't given, so `_compute` can trust both.
ProbeResult = list[tuple[int, DataSource, datetime]]
Probe = Callable[[list[Team], datetime, datetime], ProbeResult]

# Events that belong to a product other than product analytics. Everything else
# a project sends rolls up into product analytics.
_EVENT_NAME_SOURCES: dict[str, DataSource] = {
    "$exception": DataSource.ERROR_TRACKING,
    "$feature_flag_called": DataSource.FEATURE_FLAGS,
    SurveyEventName.SENT: DataSource.SURVEYS,
    SurveyEventName.SHOWN: DataSource.SURVEYS,
    SurveyEventName.DISMISSED: DataSource.SURVEYS,
}
_LLM_EVENT_PREFIX = "$ai_"

# `app_metrics2.app_source` is already a per-team, per-product activity ledger, so one
# small query covers four products that would otherwise need their own tables.
_APP_METRICS_SOURCES: dict[str, DataSource] = {
    "logs": DataSource.LOGS,
    "traces": DataSource.TRACING,
    "hog_function": DataSource.PIPELINE_DESTINATIONS,
    "hog_flow": DataSource.WORKFLOWS,
}


def get_organization_data_freshness(organization_id: str, teams: list[Team]) -> list[ProjectFreshness]:
    """Freshness for every passed team, cached per organization.

    Keyed on the team set too, since access control means two members of the same organization
    can see different projects. A visibility change moves a team in or out of that set, so the
    key changes with it rather than serving a stale verdict for the old set.
    """
    team_ids = sorted(team.id for team in teams)
    fingerprint = hashlib.sha256(",".join(str(team_id) for team_id in team_ids).encode()).hexdigest()[:16]
    cache_key = f"org_data_freshness:v{_CACHE_SCHEMA_VERSION}:{organization_id}:{fingerprint}"
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    result, degraded = _compute(teams)
    # A store being briefly unreachable reads as "no data", which is exactly the wrong answer to
    # pin for a full TTL. Cache it just long enough to absorb a burst of requests.
    safe_cache_set(cache_key, result, DEGRADED_CACHE_TTL_SECONDS if degraded else CACHE_TTL_SECONDS)
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
    for probe in _PROBES:
        try:
            for team_id, source, last_data_at in probe(teams, cutoff, horizon):
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


def _probe_events(teams: list[Team], cutoff: datetime, horizon: datetime) -> ProbeResult:
    """Event-backed products, read from the event definition catalog rather than ClickHouse.

    `posthog_eventdefinition.last_seen_at` is maintained by ingestion, which makes it far cheaper
    than a windowed events query. The tradeoff is that it is project-scoped, so environments of
    the same project share a verdict here.

    Classification happens in SQL rather than as one query per source: splitting it would make
    the `$ai_` prefix and the product-analytics residual (`NOT IN` + `NOT LIKE`) full scans of
    every definition in scope, where the grouped form reads them once.
    """
    scopes: dict[int, list[Team]] = {}
    for team in teams:
        scopes.setdefault(team.project_id or team.id, []).append(team)

    source_of_name = Case(
        *[When(name=name, then=Value(source.value)) for name, source in _EVENT_NAME_SOURCES.items()],
        When(name__startswith=_LLM_EVENT_PREFIX, then=Value(DataSource.LLM_ANALYTICS.value)),
        # Product analytics is the residual: everything that is not one of the events above.
        default=Value(DataSource.PRODUCT_ANALYTICS.value),
        output_field=CharField(),
    )
    rows = (
        EventDefinition.objects.annotate(
            # Mirrors the table's own `(coalesce(project_id, team_id), name)` uniqueness: one row
            # per project, with `project_id` null on rows that predate projects.
            scope_id=Coalesce("project_id", "team_id", output_field=BigIntegerField()),
            source=source_of_name,
        )
        .filter(scope_id__in=scopes.keys(), last_seen_at__gte=cutoff, last_seen_at__lte=horizon)
        .values("scope_id", "source")
        .annotate(last_seen=Max("last_seen_at"))
    )

    return [
        (team.id, DataSource(row["source"]), row["last_seen"])
        for row in rows
        for team in scopes.get(row["scope_id"], [])
    ]


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
        (team_id, _APP_METRICS_SOURCES[app_source], _as_utc(last_data_at)) for team_id, app_source, last_data_at in rows
    ]


def _probe_data_warehouse(teams: list[Team], cutoff: datetime, horizon: datetime) -> ProbeResult:
    """Read the per-schema sync stamp rather than aggregating job history.

    `ExternalDataJob` is one row per schema per run and has no index serving a `finished_at`
    range, so a windowed max over it reads a team's whole history. `ExternalDataSchema` holds
    one row per schema off the team FK, and is what the rest of the codebase treats as "last
    successful sync".
    """
    rows = (
        ExternalDataSchema.objects.filter(
            team_id__in=[team.id for team in teams],
            last_synced_at__gte=cutoff,
            last_synced_at__lte=horizon,
        )
        .values("team_id")
        .annotate(last_synced=Max("last_synced_at"))
    )
    return [(row["team_id"], DataSource.DATA_WAREHOUSE, row["last_synced"]) for row in rows]


_PROBES: tuple[Probe, ...] = (_probe_events, _probe_session_replay, _probe_app_metrics, _probe_data_warehouse)


def _as_utc(value: datetime) -> datetime:
    """ClickHouse hands back naive datetimes; they are always UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
