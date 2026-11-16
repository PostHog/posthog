"""Roll drafted measures up into proposed metrics, and say where people use each one.

A source answers why a metric is worth proposing: a saved chart, a place in the web app, or agent
sessions. Only drafted measures get sources, so the extra read and the extra payload stay small.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.product_analytics.backend.facade.models import Insight

from ..facade.contracts import AgentSource, ChartSource, ProposedMetric, SurfaceSource, UncoveredGroup
from .query_complexity import Complexity, query_complexity

MAX_CHART_SOURCES = 5
# A read drops the charts its reader may not open, so the scan stores more than the tab shows.
STORED_CHART_SOURCES = 50
MAX_PROPOSALS = 70
# Opening or refreshing these runs a saved query again. Their queries carry no id of the notebook or
# the canvas, so each query shape in them counts once.
SAVED_QUERY_PRODUCTS = (Product.CANVAS.value, Product.NOTEBOOKS.value)
# The query log's normalized hash drops literals, so `event = 'signup'` and `event = 'login'` would share
# a shape. The measure fingerprint keeps literals, so a shape is the exact query text.
QUERY_HASH = "cityHash64(lc_query__query)"
# Each hash takes up to 22 characters of query text, so a batch stays far below the ClickHouse query size limit.
_HASH_BATCH = 50_000


@frozen
class MeasureEvidence:
    people: frozenset[str]
    shape_hashes: frozenset[int]
    agent_people: frozenset[str]
    agent_sessions: frozenset[str]
    agent_runs: int


@frozen
class ShapeSourceRow:
    query_hash: int
    insight_id: int
    dashboard_id: int
    product: str
    user_ids: frozenset[int]
    runs: int


@frozen
class ChartName:
    short_id: str
    name: str
    dashboards: Mapping[int, str]


def fetch_shape_sources(
    *,
    team: Team,
    window_start: datetime,
    window_end: datetime,
    query_hashes: set[int],
    where: str,
    parameters: dict[str, Any],
) -> list[ShapeSourceRow]:
    rows: list[tuple] = []
    hashes = sorted(query_hashes)
    for start in range(0, len(hashes), _HASH_BATCH):
        with tags_context(product=Product.DATA_CATALOG, feature=Feature.ENRICHMENT, team_id=team.id):
            # nosemgrep: clickhouse-fstring-param-audit - callers pass a module constant filter, values go in parameters
            rows += sync_execute(
                f"""
                SELECT
                    {QUERY_HASH} AS query_hash,
                    lc_insight_id,
                    lc_dashboard_id,
                    lc_product,
                    groupUniqArray(200)(lc_user_id) AS user_ids,
                    count() AS runs
                FROM query_log_archive
                WHERE {where} AND {QUERY_HASH} IN %(query_hashes)s
                GROUP BY query_hash, lc_insight_id, lc_dashboard_id, lc_product
                """,
                {
                    **parameters,
                    "team_id": team.id,
                    "window_start": window_start,
                    "window_end": window_end,
                    "query_hashes": hashes[start : start + _HASH_BATCH],
                },
                team_id=team.id,
                workload=Workload.OFFLINE,
            )
    return [
        ShapeSourceRow(
            query_hash=query_hash,
            insight_id=insight_id,
            dashboard_id=dashboard_id,
            product=product,
            user_ids=frozenset(user_ids),
            runs=runs,
        )
        for query_hash, insight_id, dashboard_id, product, user_ids, runs in rows
    ]


def fetch_chart_creators(*, team: Team, charts: set[str]) -> dict[str, str]:
    """The distinct id of who created each chart, keyed as the query log folds charts."""
    insight_ids = {int(chart.removeprefix("insight-")) for chart in charts if chart.startswith("insight-")}
    if not insight_ids:
        return {}
    rows = Insight.objects.filter(team=team, id__in=insight_ids, created_by__isnull=False).values_list(
        "id", "created_by__distinct_id"
    )
    return {f"insight-{insight_id}": distinct_id for insight_id, distinct_id in rows if distinct_id}


def fetch_chart_names(*, team: Team, insight_ids: set[int]) -> dict[int, ChartName]:
    """Names of the team's live charts and their live dashboards. A deleted chart gets no name, so it is not shown."""
    if not insight_ids:
        return {}
    # A join skips the tile manager, which hides a removed tile, so the loop applies the same two checks.
    rows = Insight.objects.filter(team=team, id__in=insight_ids, deleted=False).values_list(
        "id",
        "short_id",
        "name",
        "derived_name",
        "dashboard_tiles__dashboard_id",
        "dashboard_tiles__dashboard__name",
        "dashboard_tiles__dashboard__deleted",
        "dashboard_tiles__deleted",
    )
    charts: dict[int, tuple[str, str]] = {}
    dashboards: dict[int, dict[int, str]] = defaultdict(dict)
    for insight_id, short_id, name, derived_name, dashboard_id, dashboard_name, dashboard_deleted, tile_deleted in rows:
        charts[insight_id] = (short_id, name or derived_name or "Unnamed chart")
        if dashboard_id and not dashboard_deleted and not tile_deleted:
            dashboards[insight_id][dashboard_id] = dashboard_name or "Unnamed dashboard"
    return {
        insight_id: ChartName(short_id=short_id, name=name, dashboards=dashboards[insight_id])
        for insight_id, (short_id, name) in charts.items()
    }


def _chart_sources(
    rows: Iterable[ShapeSourceRow], names: Mapping[int, ChartName], people_of: Mapping[int, str]
) -> list[ChartSource]:
    people: dict[tuple[int, int], set[str]] = defaultdict(set)
    for row in rows:
        if row.insight_id in names:
            # A dashboard that no longer holds the chart has no name to show or page to open, so its
            # views join the chart's own line.
            dashboard_id = row.dashboard_id if row.dashboard_id in names[row.insight_id].dashboards else 0
            people[(row.insight_id, dashboard_id)].update(
                people_of[user_id] for user_id in row.user_ids if user_id in people_of
            )
    sources = []
    for (insight_id, dashboard_id), chart_people in people.items():
        chart = names[insight_id]
        dashboard_name = chart.dashboards.get(dashboard_id)
        sources.append(
            ChartSource(
                insight_short_id=chart.short_id,
                insight_name=chart.name,
                dashboard_id=dashboard_id if dashboard_name else None,
                dashboard_name=dashboard_name,
                people=len(chart_people),
            )
        )
    sources.sort(key=lambda source: (-source.people, source.insight_name, source.dashboard_id or 0))
    return sources


def _surface_sources(rows: Iterable[ShapeSourceRow], people_of: Mapping[int, str]) -> list[SurfaceSource]:
    runs: dict[str, int] = defaultdict(int)
    people: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if not row.insight_id and not row.dashboard_id:
            runs[row.product] += row.runs
            people[row.product].update(people_of[user_id] for user_id in row.user_ids if user_id in people_of)
    sources = [
        SurfaceSource(product=product, people=len(people[product]), runs=surface_runs)
        for product, surface_runs in runs.items()
    ]
    sources.sort(key=lambda source: (-source.people, -source.runs, source.product))
    return sources


def build_proposed_metrics(
    drafted: Iterable[UncoveredGroup],
    evidence: Mapping[str, MeasureEvidence],
    rows: Iterable[ShapeSourceRow],
    names: Mapping[int, ChartName],
    people_of: Mapping[int, str],
) -> list[ProposedMetric]:
    """One proposal per draft, ranked by complexity, then the people who built it, then built count, then views. Groups that share a draft are one measure written several ways."""
    # Two merge keys can get the same name from the drafter, so the definition keeps them apart.
    by_draft: dict[tuple[str, str], list[UncoveredGroup]] = defaultdict(list)
    for group in drafted:
        if group.draft_name:
            by_draft[(group.draft_name, group.draft_definition or "")].append(group)
    rows_by_hash: dict[int, list[ShapeSourceRow]] = defaultdict(list)
    for row in rows:
        rows_by_hash[row.query_hash].append(row)

    proposals = []
    for (name, _definition), groups in by_draft.items():
        items = [evidence[group.fingerprint_digest] for group in groups]
        # A query that computes several measures of one proposal still ran once, so its rows count once.
        shape_hashes = frozenset().union(*(item.shape_hashes for item in items))
        shape_rows = [row for query_hash in shape_hashes for row in rows_by_hash[query_hash]]
        charts = _chart_sources(shape_rows, names, people_of)
        agent_runs = max(item.agent_runs for item in items)
        definition = groups[0].draft_definition or ""
        # The draft is the measure alone, so it rates what a canonical definition would hold.
        rated = query_complexity(definition) if definition else Complexity.UNKNOWN
        proposals.append(
            ProposedMetric(
                name=name,
                description=groups[0].draft_description or "",
                definition=definition,
                measures=len(groups),
                people=len(frozenset().union(*(item.people for item in items))),
                built=max(group.built for group in groups),
                views=max(group.views for group in groups),
                complexity=rated if rated != Complexity.UNKNOWN else max(group.complexity for group in groups),
                charts=charts[:STORED_CHART_SOURCES],
                other_charts=max(0, len(charts) - STORED_CHART_SOURCES),
                surfaces=_surface_sources(shape_rows, people_of),
                agents=(
                    AgentSource(
                        people=len(frozenset().union(*(item.agent_people for item in items))),
                        sessions=len(frozenset().union(*(item.agent_sessions for item in items))),
                        runs=agent_runs,
                    )
                    if agent_runs
                    else None
                ),
                fingerprint_digests=[group.fingerprint_digest for group in groups],
            )
        )
    proposals.sort(
        key=lambda proposal: (
            -proposal.complexity,
            -proposal.people,
            -proposal.built,
            -proposal.views,
            proposal.name,
            proposal.definition,
        )
    )
    return proposals[:MAX_PROPOSALS]
