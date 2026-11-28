"""Named query batches for checking which HogQL queries the multi-query planner shares.

Each batch is data: its queries, and the groups each sharing rule is expected to form once the queries are
prepared (resolved) the way `HogQLQueryExecutor.prepare_for_sharing` hands them to the planner. Queries that no
rule groups run separately, and a batch may also pin the reason a rule gives for refusing one of them.
"""

from collections.abc import Iterator
from dataclasses import field, replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from posthog.schema import DateRange, EventsNode, IntervalType, TrendsQuery

from posthog.hogql.multi_query import SharingQuery

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models.team import Team


@frozen
class HogQLSource:
    query_id: str
    hogql: str


@frozen
class TrendsSource:
    """Expands to one query per series, named `<query_id>[<series index>]`, as `TrendsQueryRunner` builds them."""

    query_id: str
    query: TrendsQuery


@frozen
class ExpectedGroup:
    rule: str
    query_ids: tuple[str, ...]


@frozen
class ExpectedRejection:
    query_id: str
    rule: str
    reason: str
    # Dashboards drop an explicit LIMIT before planning when the unlimited query would fuse, so the reason that
    # decides a dashboard tile is the one given for the query without its LIMIT.
    limit_lifted: bool = False


@frozen
class CorpusBatch:
    name: str
    description: str
    sources: tuple[HogQLSource | TrendsSource, ...]
    expected_groups: tuple[ExpectedGroup, ...]
    expected_rejections: tuple[ExpectedRejection, ...] = field(default=())


@frozen
class DateWindow:
    start: date
    days: int

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days)

    def literal(self, day: date) -> str:
        return f"'{day.isoformat()} 00:00:00'"

    def where(self, start: date | None = None, *, table: str = "") -> str:
        column = f"{table}.timestamp" if table else "timestamp"
        return f"{column} >= {self.literal(start or self.start)} AND {column} < {self.literal(self.end)}"


DEFAULT_WINDOW = DateWindow(start=date(2026, 1, 1), days=7)


def _daily(window: DateWindow, alias: str, event: str) -> str:
    return (
        f"SELECT toDate(timestamp) AS day, count() AS {alias} FROM events "
        f"WHERE event = '{event}' AND {window.where()} GROUP BY toDate(timestamp) ORDER BY day"
    )


def _top_events(window: DateWindow, order: str) -> str:
    return (
        "SELECT event, count() AS events, uniqExact(distinct_id) AS people FROM events "
        f"WHERE {window.where()} GROUP BY event ORDER BY {order} DESC, event LIMIT 3"
    )


def _trends(window: DateWindow, *events: str) -> TrendsQuery:
    return TrendsQuery(
        series=[EventsNode(event=event) for event in events],
        interval=IntervalType.DAY,
        # Without explicitDate, a date-only date_to runs to the end of that day.
        dateRange=DateRange(date_from=window.start.isoformat(), date_to=(window.end - timedelta(days=1)).isoformat()),
    )


def build_corpus(window: DateWindow = DEFAULT_WINDOW) -> tuple[CorpusBatch, ...]:
    pageviews = f"SELECT count() AS pageviews FROM events WHERE event = '$pageview' AND {window.where()}"
    late_start = window.start + timedelta(days=window.days - 3)
    return (
        CorpusBatch(
            name="daily_counts",
            description="Two daily event counts over the same window",
            sources=(
                HogQLSource(query_id="daily_pageviews", hogql=_daily(window, "pageviews", "$pageview")),
                HogQLSource(query_id="daily_signups", hogql=_daily(window, "signups", "signup")),
            ),
            expected_groups=(ExpectedGroup(rule="count_fusion", query_ids=("daily_pageviews", "daily_signups")),),
        ),
        CorpusBatch(
            name="property_filter",
            description="A total and the same total narrowed by an event property",
            sources=(
                HogQLSource(query_id="pageviews", hogql=pageviews),
                HogQLSource(query_id="chrome_pageviews", hogql=f"{pageviews} AND properties.$browser = 'Chrome'"),
            ),
            expected_groups=(ExpectedGroup(rule="count_fusion", query_ids=("pageviews", "chrome_pageviews")),),
        ),
        CorpusBatch(
            name="duplicate_tiles",
            description="The same query on two tiles",
            sources=(
                HogQLSource(query_id="first_tile", hogql=pageviews),
                HogQLSource(query_id="second_tile", hogql=pageviews),
            ),
            expected_groups=(ExpectedGroup(rule="count_fusion", query_ids=("first_tile", "second_tile")),),
        ),
        CorpusBatch(
            name="overlapping_windows",
            description="One count over the whole window and one over its last three days",
            sources=(
                HogQLSource(query_id="week_pageviews", hogql=pageviews),
                HogQLSource(
                    query_id="recent_pageviews",
                    hogql=f"SELECT count() AS pageviews FROM events WHERE event = '$pageview' AND {window.where(late_start)}",
                ),
            ),
            expected_groups=(ExpectedGroup(rule="count_fusion", query_ids=("week_pageviews", "recent_pageviews")),),
        ),
        CorpusBatch(
            name="top_events",
            description="The same aggregation ranked two ways",
            sources=(
                HogQLSource(query_id="most_events", hogql=_top_events(window, "events")),
                HogQLSource(query_id="most_people", hogql=_top_events(window, "people")),
            ),
            expected_groups=(ExpectedGroup(rule="same_aggregation_top_n", query_ids=("most_events", "most_people")),),
        ),
        CorpusBatch(
            name="table_alias",
            description="Two counts that read events through a table alias",
            sources=(
                HogQLSource(
                    query_id="aliased_pageviews",
                    hogql=f"SELECT count() AS n FROM events AS e WHERE e.event = '$pageview' AND {window.where(table='e')}",
                ),
                HogQLSource(
                    query_id="aliased_signups",
                    hogql=f"SELECT count() AS n FROM events AS e WHERE e.event = 'signup' AND {window.where(table='e')}",
                ),
            ),
            expected_groups=(),
            # The resolver keeps the user's table alias in the prepared form.
            expected_rejections=(
                ExpectedRejection(
                    query_id="aliased_pageviews",
                    rule="count_fusion",
                    reason="only an unaliased events source without joins or sampling can combine",
                ),
            ),
        ),
        CorpusBatch(
            name="unique_users",
            description="Daily unique users for two events, which no rule supports",
            sources=tuple(
                HogQLSource(
                    query_id=f"{event}_users",
                    hogql=f"SELECT toDate(timestamp) AS day, uniq(person_id) AS users FROM events WHERE event = '{event}' "
                    f"AND {window.where()} GROUP BY toDate(timestamp) ORDER BY day",
                )
                for event in ("purchase", "signup")
            ),
            expected_groups=(),
        ),
        CorpusBatch(
            name="trends_series",
            description="A trends insight with two series, run as one query per series",
            sources=(TrendsSource(query_id="trends", query=_trends(window, "$pageview", "signup")),),
            expected_groups=(),
            # The runner gives every series LIMIT 50000. Without it, the nested series query still fails the
            # source check, so lifting the limit the way dashboards do changes the reason, not the outcome.
            expected_rejections=(
                ExpectedRejection(
                    query_id="trends[0]",
                    rule="count_fusion",
                    reason="limits, settings, CTEs, and other SELECT clauses run separately",
                ),
                ExpectedRejection(
                    query_id="trends[0]",
                    rule="count_fusion",
                    reason="only an unaliased events source without joins or sampling can combine",
                    limit_lifted=True,
                ),
            ),
        ),
        CorpusBatch(
            name="mixed_dashboard",
            description="A dashboard mixing daily counts, a ranked pair and an unsupported aggregation",
            sources=(
                HogQLSource(query_id="daily_pageviews", hogql=_daily(window, "pageviews", "$pageview")),
                HogQLSource(query_id="most_events", hogql=_top_events(window, "events")),
                HogQLSource(
                    query_id="purchase_users",
                    hogql=f"SELECT uniq(person_id) AS users FROM events WHERE event = 'purchase' AND {window.where()}",
                ),
                HogQLSource(query_id="daily_signups", hogql=_daily(window, "signups", "signup")),
                HogQLSource(query_id="most_people", hogql=_top_events(window, "people")),
            ),
            expected_groups=(
                ExpectedGroup(rule="count_fusion", query_ids=("daily_pageviews", "daily_signups")),
                ExpectedGroup(rule="same_aggregation_top_n", query_ids=("most_events", "most_people")),
            ),
        ),
    )


def prepare_batch(
    batch: CorpusBatch, team: "Team", *, scope_key: str, force_sharing: bool = False
) -> list[SharingQuery]:
    """Prepare every query in one batch through the same compile path HogQL execution uses.

    `force_sharing` ignores the team's feature flag, to see what the planner would do where the flag is off.
    """
    from posthog.hogql.query import HogQLQueryExecutor  # noqa: PLC0415 -- requires django.setup()

    from products.product_analytics.backend.facade.queries import TrendsQueryRunner  # noqa: PLC0415

    prepared: list[SharingQuery] = []
    for source in batch.sources:
        if isinstance(source, HogQLSource):
            executor = HogQLQueryExecutor(query=source.hogql, team=team)
            prepared.append(executor.prepare_for_sharing(query_id=source.query_id, scope_key=scope_key))
            continue
        runner = TrendsQueryRunner(query=source.query, team=team)
        for index, series_query in enumerate(runner.to_queries()):
            executor = HogQLQueryExecutor(
                query_type="TrendsQuery",
                query=series_query,
                team=team,
                modifiers=runner.modifiers,
                limit_context=runner.limit_context,
                context=runner.build_hogql_context(),
            )
            prepared.append(executor.prepare_for_sharing(query_id=f"{source.query_id}[{index}]", scope_key=scope_key))
    return [replace(query, sharing_enabled=True) for query in prepared] if force_sharing else prepared


def synthetic_events(team: "Team", window: DateWindow, count: int) -> Iterator[dict[str, Any]]:
    """Deterministic events spread evenly across the window, in the shape `bulk_create_events` takes."""
    events = ("$pageview", "$pageview", "$pageview", "signup", "purchase", "$autocapture")
    browsers = ("Chrome", "Chrome", "Firefox", "Safari")
    seconds = window.days * 86_400
    start = datetime(window.start.year, window.start.month, window.start.day, tzinfo=UTC)
    for index in range(count):
        yield {
            "event": events[index % len(events)],
            "distinct_id": f"user_{(index * 7919) % max(count // 20, 1)}",
            "team": team,
            "timestamp": start + timedelta(seconds=(index * seconds) // count),
            "properties": {"$browser": browsers[(index // 3) % len(browsers)]},
        }
