"""
Per-project data freshness: is anything at all still reaching this project?

Products declare what counts as their data in `products/<name>/backend/data_freshness.py`,
discovered the same way `routes.py` is. This module only runs the shared queries and combines
the answers.

Runs on an interactive path, so declarations are grouped by datastore rather than by product:
event-backed products fold into one query, `app_metrics2`-backed ones into a second, and only
a product neither can answer brings its own probe.

`last_data_at` is `None` for "nothing within `LOOKBACK_DAYS`", not "never" — `Freshness.NEVER`
is the only claim made about all of time, and it leans on `Team.ingested_event`.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache, partial
from typing import Optional

from django.db.models import BigIntegerField, Case, CharField, Max, Value, When
from django.db.models.functions import Coalesce

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.utils import execute_with_timeout
from posthog.products import load_product_modules
from posthog.schema_enums import ProductKey
from posthog.utils import ensure_utc, get_safe_cache, safe_cache_set

from products.event_definitions.backend.models.event_definition import EventDefinition

logger = structlog.get_logger(__name__)

LOOKBACK_DAYS = 30
# Shorter than the lookback, so a stale project can still say roughly how long it has been quiet.
QUIET_AFTER_DAYS = 7

CACHE_TTL_SECONDS = 10 * 60
# Bump when ProjectFreshness or SourceFreshness change shape: cached values are pickled, so old
# entries would otherwise unpickle missing a field.
_CACHE_SCHEMA_VERSION = 1

# Backstops for a pathological org, not a latency budget. Postgres has no server-side
# statement_timeout here, and the ClickHouse cluster's failure mode is concurrent IO-heavy
# reads, so bytes are capped harder than time.
POSTGRES_TIMEOUT_MS = 15_000
CLICKHOUSE_SETTINGS = {"max_execution_time": 30, "max_bytes_to_read": 10_000_000_000}


class Freshness(StrEnum):
    """The project-level verdict, part of the API contract.

    Three states on purpose: a project still receiving one kind of data is in use even if
    another kind stopped, so per-source decay doesn't get its own verdict.
    """

    # Never ingested anything at all. Unstarted, not stale.
    NEVER = "never"
    LIVE = "live"
    STALE = "stale"


@dataclass(frozen=True, kw_only=True)
class ProbeWindow:
    """The time bounds every probe works within. Keyword-only because all three are datetimes."""

    cutoff: datetime
    # Data at least this recent makes a project live. Probes may answer this window first.
    quiet_before: datetime
    # Clock-skew ceiling, so one future-stamped row can't pin a dead project to "live".
    horizon: datetime


# Returns the last time each team received data, omitting teams with none.
SourceProbe = Callable[[list[int], ProbeWindow], dict[int, datetime]]


@dataclass(frozen=True, kw_only=True)
class DataSourceSpec:
    """How one product tells whether a project received its kind of data recently.

    Declare as `DATA_SOURCES` in `products/<name>/backend/data_freshness.py`, picking the
    cheapest that fits: `event_names`/`event_prefix` and `app_metrics_source` each fold into a
    shared query, `probe` runs your own. `is_residual` claims every event name nobody else does.
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


# Probes never emit a null timestamp or a team they weren't given, so `_compute` trusts both.
ProbeResult = list[tuple[int, ProductKey, datetime]]


@lru_cache(maxsize=1)
def discover_data_sources() -> tuple[DataSourceSpec, ...]:
    """Collect every product's `DATA_SOURCES`."""
    specs: list[DataSourceSpec] = []
    for module in load_product_modules("data_freshness"):
        specs.extend(getattr(module, "DATA_SOURCES", []))
    return tuple(specs)


def get_organization_data_freshness(organization_id: str, teams: list[Team]) -> list[ProjectFreshness]:
    """Freshness for every passed team, cached per organization.

    Keyed on the team set too, since access control means two members see different projects,
    and a visibility change moves a team in or out of that set.
    """
    team_ids = sorted(team.id for team in teams)
    fingerprint = hashlib.sha256(",".join(str(team_id) for team_id in team_ids).encode()).hexdigest()[:16]
    cache_key = f"org_data_freshness:v{_CACHE_SCHEMA_VERSION}:{organization_id}:{fingerprint}"
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    result = _compute(teams)
    safe_cache_set(cache_key, result, CACHE_TTL_SECONDS)
    return result


def _compute(teams: list[Team]) -> list[ProjectFreshness]:
    if not teams:
        return []

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

    return reportable([derive_freshness(team, by_team[team.id], quiet_before) for team in teams], degraded=degraded)


def reportable(results: list[ProjectFreshness], *, degraded: bool) -> list[ProjectFreshness]:
    """Drop verdicts a failed probe could have changed.

    Finding recent data stays true whatever else broke, but finding none is indistinguishable
    from not having been able to look, so those projects say nothing rather than warn wrongly.
    """
    if not degraded:
        return results
    return [result for result in results if result.freshness == Freshness.LIVE]


def _probes(
    specs: tuple[DataSourceSpec, ...], teams: list[Team], window: ProbeWindow
) -> list[tuple[str, Callable[[], ProbeResult]]]:
    """The two shared queries, plus one per product that brought its own. Isolated separately."""
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
        # The only unbounded signal available, so it's what separates never-started from
        # data older than the lookback window.
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

    `last_seen_at` is maintained by ingestion, so this is far cheaper than a windowed events
    query. It's project-scoped though, so environments of one project share a verdict here.

    Classifying in SQL rather than per product matters: splitting it would turn the prefix and
    the residual bucket into full scans of every definition in scope.
    """
    scopes: dict[int, list[Team]] = {}
    for team in teams:
        scopes.setdefault(team.project_id or team.id, []).append(team)

    # Exact names before prefixes, so a specific claim beats a prefix it sits under.
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
            # Mirrors the table's `(coalesce(project_id, team_id), name)` unique index.
            scope_id=Coalesce("project_id", "team_id", output_field=BigIntegerField()),
            source=Case(*whens, default=Value(residual), output_field=CharField()),
        )
        .filter(scope_id__in=scopes.keys(), last_seen_at__gte=window.cutoff, last_seen_at__lte=window.horizon)
        .values("scope_id", "source")
        .annotate(last_seen=Max("last_seen_at"))
    )

    # Evaluated inside the block: the timeout is transaction-local, so a lazily-built queryset
    # would escape it.
    with execute_with_timeout(POSTGRES_TIMEOUT_MS):
        rows = list(queryset)
    return [
        (team.id, ProductKey(row["source"]), row["last_seen"])
        for row in rows
        if row["source"]  # empty when no product claims the residual
        for team in scopes.get(row["scope_id"], [])
    ]


def _probe_app_metrics(specs: tuple[DataSourceSpec, ...], teams: list[Team], window: ProbeWindow) -> ProbeResult:
    """Every `app_metrics2`-backed product, in one query.

    That table is already a per-team, per-product activity ledger sorted on `team_id` first.
    """
    products_by_app_source = {spec.app_metrics_source: spec.product for spec in specs if spec.app_metrics_source}
    if not products_by_app_source:
        return []

    # Kept off this module's import path, which product declaration modules pull in.
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
