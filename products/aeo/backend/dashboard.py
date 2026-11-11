"""The "AI visibility weekly" dashboard: SQL insights over `system.aeo_citation_checks`.

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

# A brand a person ignored counts as neither own nor competitor.
_BRANDS_OF_KIND = "SELECT groupArray({expr}) FROM system.aeo_brands WHERE kind = '{kind}' AND status != 'ignored'"
# A citation-sourced domain comes from a third-party URL, whose host can hold characters a real domain label
# cannot, such as "|" or "(". A brand name goes into a regex unescaped, so a name with any character other than
# a letter, a digit or a hyphen is dropped. One such name could otherwise mark every prompt as branded, or make
# the regex invalid and fail the tile.
_BRAND_NAMES = (
    r"SELECT arrayFilter(name -> match(name, '^[\\p{L}\\p{N}-]+$'), groupArray(lower(splitByChar('.', domain)[1]))) "
    "FROM system.aeo_brands WHERE kind = 'own' AND status != 'ignored'"
)
_OWN_DOMAINS = _BRANDS_OF_KIND.format(expr="lower(domain)", kind="own")
_COMPETITOR_DOMAINS = _BRANDS_OF_KIND.format(expr="lower(domain)", kind="competitor")
_BRAND_REGEX = r"concat('(?i)\\b(', arrayStringConcat(brand_names, '|'), ')\\b')"
_NAMES_BRAND = "notEmpty(brand_names) AND match({field}, brand_regex)"


def _answers(days: int) -> str:
    """Answered non-branded checks from the last `days` complete days in the project's timezone.

    `days_ago` is 1 for yesterday, so days 1-7 are the report week and days 8-14 the week before.
    An answer is cited when it cites a page on a current own domain. The stored `cited` column is not used,
    because it was computed at ingestion from the domains configured then, and the pages tile reads the catalog.
    A cited answer counts as a mention even when its text only carries the URL, as in `brand.mention_filter`.
    """
    return f"""
        WITH ({_BRAND_NAMES}) AS brand_names, {_BRAND_REGEX} AS brand_regex, ({_OWN_DOMAINS}) AS own_domains
        SELECT
            dateDiff('day', toDate(created_at), toDate(now())) AS days_ago,
            prompt_topic,
            arrayDistinct(JSONExtract(ifNull(cited_urls, '[]'), 'Array(String)')) AS urls,
            arrayExists(
                url -> arrayExists(d -> lower(domain(url)) = d OR endsWith(lower(domain(url)), concat('.', d)), own_domains),
                urls
            ) AS cites_own,
            cites_own OR ({_NAMES_BRAND.format(field="ifNull(answer_text, '')")}) AS mentioned
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

SCORECARD_SQL = f"""
SELECT
    {_rate("mentioned", _THIS_WEEK)} AS visibility,
    {_rate("mentioned", _WEEK_BEFORE)} AS previous_visibility,
    round(visibility - previous_visibility, 1) AS visibility_change,
    {_rate("cites_own", _THIS_WEEK)} AS citation_rate,
    {_rate("cites_own", _WEEK_BEFORE)} AS previous_citation_rate,
    round(citation_rate - previous_citation_rate, 1) AS citation_rate_change,
    countIf({_THIS_WEEK}) AS answers,
    countIf({_WEEK_BEFORE}) AS previous_answers
FROM ({_answers(14)})
"""

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

# Weeks end yesterday, so the last point is the scorecard's report week.
TREND_SQL = f"""
SELECT
    toDate(now()) - 1 - 7 * intDiv(days_ago - 1, 7) AS week_ending,
    round(100 * countIf(mentioned) / count(), 1) AS visibility,
    round(100 * countIf(cites_own) / count(), 1) AS citation_rate,
    count() AS answers
FROM ({_answers(7 * TREND_WEEKS)})
GROUP BY week_ending
ORDER BY week_ending
"""

SUBSCRIBE_TEXT = """\
**AI visibility weekly** compares the last 7 complete days with the 7 days before, over non-branded prompts: prompts that don't name your brand. Visibility is the share of answers that mention your brand or cite your site. Changes are in percentage points.

Own and competitor pages come from the brand catalog, and branded prompts from the names of your own brands, so the numbers follow your catalog edits.

**Get it every week:** select **Subscribe** at the top of this dashboard, choose Slack or email, and set it to repeat weekly. Turn on **Include an automatic AI summary** to get suggested actions with each delivery.
"""

_TILE_HEIGHT = 5


def _sql_tile(
    name: str, description: str, query: str, *, x: int, y: int, w: int, h: int = _TILE_HEIGHT, **settings: Any
) -> dict[str, Any]:
    return {
        "type": "INSIGHT",
        "name": name,
        "description": description,
        "query": {
            "kind": "DataVisualizationNode",
            "source": {"kind": "HogQLQuery", "query": textwrap.dedent(query).strip()},
            **settings,
        },
        "layouts": {"sm": {"x": x, "y": y, "w": w, "h": h}},
        "color": None,
    }


def build_dashboard_tiles() -> list[dict[str, Any]]:
    return [
        {
            "type": "TEXT",
            "body": SUBSCRIBE_TEXT,
            "layouts": {"sm": {"x": 0, "y": 0, "w": 12, "h": 3}},
            "color": None,
        },
        _sql_tile(
            "Non-branded visibility this week",
            "Mention rate and citation rate in percent over the last 7 complete days, against the 7 days before, "
            "with the number of answers behind each.",
            SCORECARD_SQL,
            x=0,
            y=3,
            w=6,
        ),
        _sql_tile(
            "Visibility trend",
            f"Weekly non-branded mention rate and citation rate in percent over the last {TREND_WEEKS} weeks.",
            TREND_SQL,
            x=6,
            y=3,
            w=6,
            display="ActionsLineGraph",
            chartSettings={
                "xAxis": {"column": "week_ending"},
                "yAxis": [{"column": "visibility"}, {"column": "citation_rate"}],
            },
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
