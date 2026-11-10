"""The "AI visibility weekly" dashboard: insights over `system.aeo_citation_checks`.

The rates are Trends insights, so people can change their dates and breakdowns
like any other insight. The tiles Trends cannot express, a change in points per
topic and the pages to watch, are SQL insights.

Every query reads the brand catalog from `system.aeo_brands` when it runs, so the
branded split and the own and competitor pages follow catalog edits without
anyone touching the dashboard. A prompt is branded when it names one of the
team's own brands, as in `brand.py`: the first label of an own domain, as a
word, case ignored.
"""

from __future__ import annotations

import textwrap
from typing import Any

from django.db import transaction

from posthog.models.team import Team
from posthog.models.user import User

from products.dashboards.backend.facade.api import DashboardRef, create_dashboard_from_tiles

DASHBOARD_NAME = "AI visibility weekly"
DASHBOARD_TAG = "ai-visibility"
TREND_WEEKS = 8
CHECKS_TABLE = "system.aeo_citation_checks"

# A brand a person ignored counts as neither own nor competitor.
_BRANDS_OF_KIND = "SELECT groupArray({expr}) FROM system.aeo_brands WHERE kind = '{kind}' AND status != 'ignored'"
_BRAND_NAMES = _BRANDS_OF_KIND.format(expr="lower(splitByChar('.', domain)[1])", kind="own")
_OWN_DOMAINS = _BRANDS_OF_KIND.format(expr="lower(domain)", kind="own")
_COMPETITOR_DOMAINS = _BRANDS_OF_KIND.format(expr="lower(domain)", kind="competitor")
# Domain labels are letters, digits and hyphens, so the names need no regex escaping.
_BRAND_REGEX = r"concat('(?i)\\b(', arrayStringConcat(brand_names, '|'), ')\\b')"
_NAMES_BRAND = "notEmpty(brand_names) AND match({field}, brand_regex)"

# The same rules as HogQL filters on a Trends series, which has no WITH clause to hold the names.
# `arrayExists` over an empty catalog is false, so without an own brand nothing names the brand.
_TRENDS_NAMES_BRAND = (
    r"arrayExists(name -> match({field}, concat('(?i)\\b', name, '\\b')), "
    f"({_BRAND_NAMES}))"
)
_TRENDS_ANSWERED_NON_BRANDED = f"NOT check_failed AND NOT {_TRENDS_NAMES_BRAND.format(field='prompt_text')}"
_TRENDS_MENTIONED = f"cited OR {_TRENDS_NAMES_BRAND.format(field="ifNull(answer_text, '')")}"


def _answers(days: int) -> str:
    """Answered non-branded checks from the last `days` complete days in the project's timezone.

    `days_ago` is 1 for yesterday, so days 1-7 are the report week and days 8-14 the week before.
    A cited answer counts as a mention even when its text only carries the URL, as in `brand.mention_filter`.
    """
    return f"""
        WITH ({_BRAND_NAMES}) AS brand_names, {_BRAND_REGEX} AS brand_regex
        SELECT
            dateDiff('day', toDate(created_at), toDate(now())) AS days_ago,
            prompt_topic,
            cited,
            cited OR ({_NAMES_BRAND.format(field="ifNull(answer_text, '')")}) AS mentioned,
            arrayDistinct(JSONExtract(ifNull(cited_urls, '[]'), 'Array(String)')) AS urls
        FROM system.aeo_citation_checks
        WHERE NOT check_failed
            AND created_at >= toStartOfDay(now()) - INTERVAL {days} DAY
            AND created_at < toStartOfDay(now())
            AND NOT ({_NAMES_BRAND.format(field="prompt_text")})
    """


def _rate(condition: str, week: str) -> str:
    return f"round(100 * countIf({week} AND {condition}) / nullIf(countIf({week}), 0), 1)"


_THIS_WEEK = "days_ago <= 7"
_WEEK_BEFORE = "days_ago > 7"

TOPICS_SQL = f"""
SELECT
    if(prompt_topic = '', 'No topic', prompt_topic) AS topic,
    {_rate("mentioned", _THIS_WEEK)} AS visibility,
    {_rate("mentioned", _WEEK_BEFORE)} AS previous_visibility,
    round(visibility - previous_visibility, 1) AS change,
    countIf({_THIS_WEEK}) AS answers
FROM ({_answers(14)})
GROUP BY prompt_topic
HAVING answers > 0
ORDER BY abs(change) DESC NULLS LAST, answers DESC, topic
LIMIT 100
"""

# A page's citation rate is the share of its topic's answers that cited it, so a topic that ran fewer prompts
# this week does not read as every page in it losing citations.
PAGES_SQL = f"""
WITH
    ({_OWN_DOMAINS}) AS own_domains,
    ({_COMPETITOR_DOMAINS}) AS competitor_domains
SELECT topic, role, url, citation_rate, previous_citation_rate, change
FROM (
    SELECT
        if(pages.prompt_topic = '', 'No topic', pages.prompt_topic) AS topic,
        pages.url AS url,
        lower(domain(url)) AS host,
        round(100 * pages.cites / topics.answers, 1) AS citation_rate,
        round(100 * pages.previous_cites / topics.previous_answers, 1) AS previous_citation_rate,
        round(citation_rate - previous_citation_rate, 1) AS change,
        arrayExists(d -> host = d OR endsWith(host, concat('.', d)), own_domains) AS is_own,
        arrayExists(d -> host = d OR endsWith(host, concat('.', d)), competitor_domains) AS is_competitor,
        multiIf(
            is_own AND change > 0, 'Own page gained',
            is_own AND change < 0, 'Own page lost',
            is_competitor AND NOT is_own AND change > 0, 'Competitor page gained',
            ''
        ) AS role,
        row_number() OVER (PARTITION BY topic, role ORDER BY abs(change) DESC, url) AS rank
    FROM (
        SELECT prompt_topic, url, countIf({_THIS_WEEK}) AS cites, countIf({_WEEK_BEFORE}) AS previous_cites
        FROM ({_answers(14)})
        ARRAY JOIN urls AS url
        GROUP BY prompt_topic, url
    ) AS pages
    JOIN (
        SELECT prompt_topic, countIf({_THIS_WEEK}) AS answers, countIf({_WEEK_BEFORE}) AS previous_answers
        FROM ({_answers(14)})
        GROUP BY prompt_topic
        HAVING answers > 0 AND previous_answers > 0
    ) AS topics ON pages.prompt_topic = topics.prompt_topic
)
WHERE role != '' AND rank = 1
ORDER BY topic, role
LIMIT 300
"""

# Trends counts days in the project's timezone. "-7d" to "-1d" is the last 7 complete days, and the
# previous period the comparison picks is the 7 days before, as in the SQL tiles.
_LAST_WEEK = {"date_from": "-7d", "date_to": "-1d"}


def _checks_series(condition: str | None = None) -> dict[str, Any]:
    properties = [{"type": "hogql", "key": _TRENDS_ANSWERED_NON_BRANDED}]
    if condition:
        properties.append({"type": "hogql", "key": condition})
    return {
        "kind": "DataWarehouseNode",
        "id": CHECKS_TABLE,
        "table_name": CHECKS_TABLE,
        "timestamp_field": "timestamp",
        "id_field": "id",
        "distinct_id_field": "prompt_id",
        "math": "total",
        "properties": properties,
    }


def _rate_query(
    formulas: dict[str, str],
    *,
    display: str,
    date_range: dict[str, Any],
    interval: str,
    compare: bool = False,
) -> dict[str, Any]:
    """A Trends query over answered non-branded checks: series A counts every answer, B the ones that
    mention the brand and C the ones that cite the site. `formulas` maps each display name to a rate over A."""
    return {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "series": [_checks_series(), _checks_series(_TRENDS_MENTIONED), _checks_series("cited")],
            "interval": interval,
            "dateRange": date_range,
            "compareFilter": {"compare": compare},
            "trendsFilter": {
                "display": display,
                "formulaNodes": [{"formula": formula, "custom_name": name} for name, formula in formulas.items()],
                "aggregationAxisFormat": "percentage_scaled",
                "decimalPlaces": 1,
            },
        },
    }


VISIBILITY = {"Visibility": "B / A"}
CITATION_RATE = {"Citation rate": "C / A"}

VISIBILITY_QUERY = _rate_query(VISIBILITY, display="BoldNumber", date_range=_LAST_WEEK, interval="day", compare=True)
CITATION_RATE_QUERY = _rate_query(
    CITATION_RATE, display="BoldNumber", date_range=_LAST_WEEK, interval="day", compare=True
)
TREND_QUERY = _rate_query(
    VISIBILITY | CITATION_RATE,
    display="ActionsLineGraph",
    date_range={"date_from": f"-{TREND_WEEKS}w"},
    interval="week",
)

SUBSCRIBE_TEXT = """\
**AI visibility weekly** compares the last 7 complete days with the 7 days before, over non-branded prompts: prompts that don't name your brand. Visibility is the share of answers that mention your brand or cite your site. The topic changes are in percentage points.

Own and competitor pages come from the brand catalog, and branded prompts from the names of your own brands, so the numbers follow your catalog edits.

**Get it every week:** select **Subscribe** at the top of this dashboard, choose Slack or email, and set it to repeat weekly. Turn on **Include an automatic AI summary** to get suggested actions with each delivery.
"""

_TILE_HEIGHT = 5


def _tile(name: str, description: str, query: dict[str, Any], *, x: int, y: int, w: int) -> dict[str, Any]:
    return {
        "type": "INSIGHT",
        "name": name,
        "description": description,
        "query": query,
        "layouts": {"sm": {"x": x, "y": y, "w": w, "h": _TILE_HEIGHT}},
        "color": None,
    }


def _sql_tile(name: str, description: str, query: str, *, x: int, y: int, w: int) -> dict[str, Any]:
    source = {"kind": "HogQLQuery", "query": textwrap.dedent(query).strip()}
    return _tile(name, description, {"kind": "DataVisualizationNode", "source": source}, x=x, y=y, w=w)


def build_dashboard_tiles() -> list[dict[str, Any]]:
    return [
        {
            "type": "TEXT",
            "body": SUBSCRIBE_TEXT,
            "layouts": {"sm": {"x": 0, "y": 0, "w": 12, "h": 3}},
            "color": None,
        },
        _tile(
            "Non-branded visibility this week",
            "Share of answers that mention your brand or cite your site over the last 7 complete days, "
            "against the 7 days before.",
            VISIBILITY_QUERY,
            x=0,
            y=3,
            w=3,
        ),
        _tile(
            "Non-branded citation rate this week",
            "Share of answers that cite your site over the last 7 complete days, against the 7 days before.",
            CITATION_RATE_QUERY,
            x=3,
            y=3,
            w=3,
        ),
        _tile(
            "Visibility trend",
            f"Weekly non-branded visibility and citation rate over the last {TREND_WEEKS} weeks.",
            TREND_QUERY,
            x=6,
            y=3,
            w=6,
        ),
        _sql_tile(
            "Topics",
            "Non-branded visibility per topic this week, with the change in points against the week before. "
            "Biggest moves first.",
            TOPICS_SQL,
            x=0,
            y=8,
            w=12,
        ),
        _sql_tile(
            "Pages to watch",
            "Per topic: your page whose citation rate rose most, the one that fell most, and the competitor page "
            "that rose most. Rates are the share of the topic's answers that cited the page.",
            PAGES_SQL,
            x=0,
            y=13,
            w=12,
        ),
    ]


def create_visibility_dashboard(team: Team, user: User) -> DashboardRef:
    # Atomic, so a tile that fails to save leaves no half-built dashboard behind.
    with transaction.atomic():
        return create_dashboard_from_tiles(
            team=team,
            user=user,
            name=DASHBOARD_NAME,
            description="Weekly AI visibility over non-branded prompts: visibility, topics and pages to watch.",
            filters={},
            tiles=build_dashboard_tiles(),
            tags=[DASHBOARD_TAG],
        )
