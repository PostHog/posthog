"""
Per-project data freshness: is anything at all still reaching this project?

PostHog is multi-modal, so a single "last event" timestamp is a bad proxy for a
project being alive: a project can be busy on session replay and logs while
product analytics has been silent for a month.

Products declare what "recent data" means for them; this module only knows how
to run the shared queries and combine the answers. A product declares
`DATA_SOURCES` in `products/<name>/backend/data_freshness.py` and is discovered
the same way `routes.py` is, so adding one takes no edit here.

Two cost constraints shape the shared queries, because this runs on an
interactive path (opening the project switcher):

  1. Declarations are grouped by datastore rather than by product, so most
     sources cost nothing extra: every event-backed product folds into one
     query over the event definition catalog, and every `app_metrics2`-backed
     one into a second. Only a product whose signal fits neither declares its
     own `probe`.
  2. Every probe is bounded to `LOOKBACK_DAYS`, and both stores have hard caps.
     Concurrent IO-heavy reads are what hurt the ClickHouse cluster, so
     `max_bytes_to_read` is the real guard and the time limits are backstops. A
     probe that trips one fails, which degrades gracefully rather than
     propagating.

The bound is why `last_data_at` is nullable per project: `None` means "nothing
within the lookback window", not "never". `Freshness.NEVER` is the only claim
this module makes about all of time, and it leans on `Team.ingested_event`.
"""

import hashlib
import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache, partial
from typing import Optional

from django.apps import apps
from django.db.models import BigIntegerField, Case, CharField, Max, Value, When
from django.db.models.functions import Coalesce

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.utils import execute_with_timeout
from posthog.schema_enums import ProductKey
from posthog.utils import ensure_utc, get_safe_cache, safe_cache_set

from products.event_definitions.backend.models.event_definition import EventDefinition

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
_CACHE_SCHEMA_VERSION = 2

# Backstops, not a latency budget: the cache means one org pays a slow compute at most once per
# TTL, so these are set well above any legitimate org and exist to stop a pathological one from
# holding a worker (Postgres has no server-side statement_timeout on this connection).
POSTGRES_TIMEOUT_MS = 15_000
CLICKHOUSE_SETTINGS = {
    "max_execution_time": 30,
    # The cluster's failure mode is concurrent IO-heavy reads, so bytes are capped harder than
    # time. One busy team is ~100 MB of replay over 30 days; anything near this ceiling is a bug.
    "max_bytes_to_read": 10_000_000_000,
}


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
class ProbeWindow:
    """The time bounds every probe works within. Keyword-only because all three are datetimes."""

    # Oldest data any probe will look at.
    cutoff: datetime
    # Data at least this recent makes a project live. Probes may answer this window first.
    quiet_before: datetime
    # Clock-skew ceiling: ingestion can stamp slightly into the future, and without this a
    # single skewed row would pin a dead project to "live" forever.
    horizon: datetime


# A product's own query, for signals neither shared query can answer. Returns the last time each
# of the given teams received data, omitting teams with none.
SourceProbe = Callable[[list[int], ProbeWindow], dict[int, datetime]]


@dataclass(frozen=True, kw_only=True)
class DataSourceSpec:
    """How one product tells whether a project has received its kind of data recently.

    Declare these as `DATA_SOURCES` in `products/<name>/backend/data_freshness.py`. Pick the
    cheapest option that fits, in this order:

      1. `event_names` / `event_prefix` — folded into one shared query over the event
         definition catalog, which is maintained by ingestion and costs nothing extra.
      2. `app_metrics_source` — folded into one shared query over `app_metrics2`, which is
         already a per-team, per-product activity ledger.
      3. `probe` — your own query. Only when neither of the above can see your data.

    `is_residual` marks the product that owns every event name no other product claims.
    """

    product: ProductKey
    event_names: tuple[str, ...] = ()
    event_prefix: str = ""
    app_metrics_source: str = ""
    probe: Optional[SourceProbe] = None
    is_residual: bool = False


@dataclass(frozen=True, kw_only=True)
class SourceFreshness:
    data_source: ProductKey
    last_data_at: datetime


@dataclass(frozen=True, kw_only=True)
class ProjectFreshness:
    team_id: int
    freshness: Freshness
    last_data_at: Optional[datetime]
    sources: list[SourceFreshness] = field(default_factory=list)


# One (team_id, product, timestamp) row per thing a probe found. Probes never emit a null
# timestamp or a team they weren't given, so `_compute` can trust both.
ProbeResult = list[tuple[int, ProductKey, datetime]]


@lru_cache(maxsize=1)
def discover_data_sources() -> tuple[DataSourceSpec, ...]:
    """Collect every product's `DATA_SOURCES`, the same way core discovers `routes.py`.

    `find_spec` rather than try/except so a real ImportError inside a product's module surfaces
    instead of being swallowed as "this product doesn't declare any".
    """
    specs: list[DataSourceSpec] = []
    for app_config in apps.get_app_configs():
        if not app_config.name.startswith("products."):
            continue
        module_name = f"{app_config.name}.data_freshness"
        if importlib.util.find_spec(module_name) is None:
            continue
        specs.extend(getattr(importlib.import_module(module_name), "DATA_SOURCES", []))
    return tuple(specs)


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
    quiet_before = now - timedelta(days=QUIET_AFTER_DAYS)
    window = ProbeWindow(
        cutoff=now - timedelta(days=LOOKBACK_DAYS),
        quiet_before=quiet_before,
        horizon=now + timedelta(days=1),
    )
    specs = discover_data_sources()

    degraded = False
    by_team: dict[int, dict[ProductKey, datetime]] = {team.id: {} for team in teams}
    for name, probe in _probes(specs, teams, window):
        try:
            for team_id, product, last_data_at in probe():
                previous = by_team[team_id].get(product)
                if previous is None or last_data_at > previous:
                    by_team[team_id][product] = last_data_at
        except Exception as e:
            # One unavailable store must not blank out every other source's verdict.
            degraded = True
            logger.warning("data_freshness_probe_failed", probe=name, error=str(e))
            capture_exception(e)

    return [derive_freshness(team, by_team[team.id], quiet_before) for team in teams], degraded


def _probes(
    specs: tuple[DataSourceSpec, ...], teams: list[Team], window: ProbeWindow
) -> list[tuple[str, Callable[[], ProbeResult]]]:
    """The two shared queries, plus one entry per product that brought its own.

    Each is isolated so a single failing store degrades only its own sources.
    """
    return [
        ("event_definitions", partial(_probe_event_definitions, specs, teams, window)),
        ("app_metrics", partial(_probe_app_metrics, specs, teams, window)),
        *(
            (spec.product.value, partial(_run_source_probe, spec, teams, window))
            for spec in specs
            if spec.probe is not None
        ),
    ]


def derive_freshness(team: Team, found: dict[ProductKey, datetime], quiet_before: datetime) -> ProjectFreshness:
    sources = sorted(
        (SourceFreshness(data_source=product, last_data_at=at) for product, at in found.items()),
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


def _probe_event_definitions(specs: tuple[DataSourceSpec, ...], teams: list[Team], window: ProbeWindow) -> ProbeResult:
    """Every event-backed product, in one query over the event definition catalog.

    `posthog_eventdefinition.last_seen_at` is maintained by ingestion, which makes it far cheaper
    than a windowed events query. The tradeoff is that it is project-scoped, so environments of
    the same project share a verdict here.

    Classification happens in SQL rather than one query per product: splitting it would make an
    open-ended prefix and the residual bucket (`NOT IN` + `NOT LIKE`) full scans of every
    definition in scope, where the grouped form reads them once.
    """
    scopes: dict[int, list[Team]] = {}
    for team in teams:
        scopes.setdefault(team.project_id or team.id, []).append(team)

    # Exact names before prefixes, so a product claiming a specific name always beats a product
    # claiming the prefix it happens to sit under.
    whens = [
        *(When(name=name, then=Value(spec.product.value)) for spec in specs for name in spec.event_names),
        *(
            When(name__startswith=spec.event_prefix, then=Value(spec.product.value))
            for spec in specs
            if spec.event_prefix
        ),
    ]
    if not whens:
        return []
    residual = next((spec.product.value for spec in specs if spec.is_residual), "")

    queryset = (
        EventDefinition.objects.annotate(
            # Mirrors the table's own `(coalesce(project_id, team_id), name)` uniqueness: one row
            # per project, with `project_id` null on rows that predate projects.
            scope_id=Coalesce("project_id", "team_id", output_field=BigIntegerField()),
            source=Case(*whens, default=Value(residual), output_field=CharField()),
        )
        .filter(scope_id__in=scopes.keys(), last_seen_at__gte=window.cutoff, last_seen_at__lte=window.horizon)
        .values("scope_id", "source")
        .annotate(last_seen=Max("last_seen_at"))
    )

    # Evaluated inside the block: the timeout is transaction-local, so it only covers the query
    # if the queryset is actually run here rather than merely built here.
    with execute_with_timeout(POSTGRES_TIMEOUT_MS):
        rows = list(queryset)
    return [
        (team.id, ProductKey(row["source"]), row["last_seen"])
        for row in rows
        if row["source"]  # no residual product declared, so unclaimed event names go nowhere
        for team in scopes.get(row["scope_id"], [])
    ]


def _probe_app_metrics(specs: tuple[DataSourceSpec, ...], teams: list[Team], window: ProbeWindow) -> ProbeResult:
    """Every `app_metrics2`-backed product, in one query.

    That table is already a per-team, per-product activity ledger sorted on `team_id` first, so
    several products fall out of a single cheap read.
    """
    products_by_app_source = {spec.app_metrics_source: spec.product for spec in specs if spec.app_metrics_source}
    if not products_by_app_source:
        return []

    # Imported here so the ClickHouse client stays off this module's import path, which product
    # declaration modules pull in.
    from posthog.clickhouse.client import sync_execute  # noqa: PLC0415
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context  # noqa: PLC0415

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
                "app_sources": list(products_by_app_source.keys()),
                "cutoff": window.cutoff,
                "horizon": window.horizon,
            },
            settings=CLICKHOUSE_SETTINGS,
        )
    return [
        (team_id, products_by_app_source[app_source], ensure_utc(last_data_at))
        for team_id, app_source, last_data_at in rows
    ]


def _run_source_probe(spec: DataSourceSpec, teams: list[Team], window: ProbeWindow) -> ProbeResult:
    assert spec.probe is not None
    found = spec.probe([team.id for team in teams], window)
    return [(team_id, spec.product, last_data_at) for team_id, last_data_at in found.items()]
