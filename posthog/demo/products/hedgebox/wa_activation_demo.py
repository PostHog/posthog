"""Web analytics activation demo: real events + persons in ClickHouse plus a
saved query that mirrors PostHog's production materialized view, feeding a
"Web analytics activation funnel" insight.

The data flow matches prod:

    events (ClickHouse) + person_properties
        └─► web_analytics_activation_base_events (DataWarehouseSavedQuery)
              └─► "Web analytics activation funnel" (Insight)

~300 synthetic orgs (one persona per org) emit ~11k events over the last 4
months, distributed across activation outcomes (never / events_only / partial /
activated / retained). Person properties (`organization_id`, `email`, `realm`,
`product_key`) and event properties (`$current_url`, `host`, `realm`,
`product_key`) are set on every event so the materialized-view SELECT resolves
identically to the prod query.

Idempotent on (team, distinct_id) and on deterministic event UUIDs derived
from (team_id, org_id, event_seq) — re-runs produce the same persons/events.

The catalog agent is expected to derive a CatalogMetric from the insight in a
separate pass — this module stops at the insight.
"""

from __future__ import annotations

import uuid as uuid_module
import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.query_tagging import tag_queries
from posthog.models.event.sql import EVENTS_DATA_TABLE
from posthog.models.event.util import create_event
from posthog.models.insight import Insight
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.team.team import Team
from posthog.models.user import User

from products.data_warehouse.backend.models import CLICKHOUSE_HOGQL_MAPPING, clean_type
from products.data_warehouse.backend.models.credential import DataWarehouseCredential
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.table import DataWarehouseTable

if TYPE_CHECKING:
    from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix

WA_DEMO_RANDOM_SEED = 137

INSIGHT_NAME = "Web analytics activation funnel"
INSIGHT_DESCRIPTION = (
    "Monthly cohorts of orgs that showed web-analytics product intent — what share sent their first event, "
    "fully activated (>5 pageviews, >3 distinct days, >3 filter clicks) within 30 days, and were retained "
    "3-4 months later."
)

# Stable namespace for deterministic event/person UUIDs so re-runs don't
# duplicate rows in ClickHouse (events are append-only).
WA_DEMO_NAMESPACE = uuid_module.UUID("a0b1c2d3-e4f5-6789-0123-456789abcdef")

# Bucketed outcomes — drives both the size and shape of each org's event stream.
# Weights chosen so the final cohort funnel lands at a believable shape:
# ~35% activation rate, ~50% retention of activated orgs.
OUTCOME_WEIGHTS: dict[str, int] = {
    "never": 25,
    "events_only": 15,
    "partial": 25,
    "activated": 25,
    "retained": 10,
}


# ----------------------------------------------------------------------------
# Stand-in for the prod activation materialized view. Selects from `events`
# joined to `persons` (PostHog auto-resolves `person.properties.X` against the
# event's `person_properties` map under person-on-events mode).
# ----------------------------------------------------------------------------


MATERIALIZED_VIEW_SQL = """
SELECT
    person.properties.organization_id AS organization_id,
    toDate(timestamp) AS event_date,
    toStartOfMonth(toDate(timestamp)) AS event_month,
    event,
    properties.$current_url AS current_url,
    properties.realm AS realm,
    properties.product_key AS product_key,
    person.properties.email AS email,
    properties.host AS host,
    distinct_id,
    timestamp
FROM events
WHERE toDate(timestamp) >= now() - toIntervalMonth(4)
    AND event IN (
        'onboarding product selected',
        'user showed product intent',
        'team member invited',
        'first team event ingested',
        'billing subscription activated',
        'visited web analytics',
        '$pageview'
    )
    AND person.properties.email IS NOT NULL
    AND person.properties.email != ''
    AND (
        CASE
            WHEN event = '$pageview' THEN properties.$current_url LIKE '%/web%'
            ELSE true
        END
    )
""".strip()

MATERIALIZED_VIEW_OUTPUT_COLUMNS: dict[str, str] = {
    "organization_id": "Nullable(String)",
    "event_date": "Date",
    "event_month": "Date",
    "event": "String",
    "current_url": "Nullable(String)",
    "realm": "Nullable(String)",
    "product_key": "Nullable(String)",
    "email": "Nullable(String)",
    "host": "Nullable(String)",
    "distinct_id": "String",
    "timestamp": "DateTime",
}

# Final activation funnel — unchanged from the prior iteration except it now
# reads from a saved query backed by `events` rather than a CSV warehouse table.
ACTIVATION_FUNNEL_SQL = """
WITH showed_intent AS (
    SELECT
        organization_id,
        start_date,
        toStartOfMonth(start_date) AS start_month
    FROM (
        SELECT
            organization_id,
            event_date AS start_date,
            row_number() OVER (PARTITION BY organization_id ORDER BY event_date) AS rn
        FROM web_analytics_activation_base_events
        WHERE (
                (event = 'onboarding product selected' AND realm = 'cloud')
                OR (event = 'user showed product intent' AND realm = 'cloud')
            )
            AND email NOT LIKE '%posthog.com%'
            AND host NOT LIKE '%localhost%'
            AND distinct_id NOT LIKE '%posthog%'
            AND product_key = 'web_analytics'
    ) AS ranked
    WHERE rn = 1
),
downfunnel AS (
    SELECT
        organization_id,
        event_date AS date_str,
        sum(event = 'first team event ingested') AS first_team_event_ingested,
        sum(event = '$pageview' AND match(current_url, 'https://(app|eu|us)\\\\.posthog\\\\.com/project/\\\\d+/web.*')) AS visited_web_analytics,
        sum(event = '$pageview' AND match(current_url, 'https://(app|eu|us)\\\\.posthog\\\\.com/project/\\\\d+/web.*filter.*$')) AS filtered_web_analytics,
        count(DISTINCT if(event = '$pageview' AND match(current_url, 'https://(app|eu|us)\\\\.posthog\\\\.com/project/\\\\d+/web.*'), event_date, NULL)) AS days_visited_web_analytics
    FROM web_analytics_activation_base_events
    WHERE event IN ('first team event ingested', '$pageview')
    GROUP BY organization_id, event_date
),
event_sent_orgs AS (
    SELECT showed_intent.organization_id
    FROM showed_intent
    JOIN downfunnel ON showed_intent.organization_id = downfunnel.organization_id
    WHERE downfunnel.date_str >= showed_intent.start_date
        AND downfunnel.date_str <= showed_intent.start_date + toIntervalDay(30)
    GROUP BY showed_intent.organization_id
    HAVING sum(coalesce(downfunnel.first_team_event_ingested, 0)) > 0
),
successful_orgs AS (
    SELECT showed_intent.organization_id
    FROM showed_intent
    JOIN downfunnel ON showed_intent.organization_id = downfunnel.organization_id
    WHERE downfunnel.date_str >= showed_intent.start_date
        AND downfunnel.date_str <= showed_intent.start_date + toIntervalDay(30)
    GROUP BY showed_intent.organization_id
    HAVING sum(coalesce(downfunnel.visited_web_analytics, 0)) > 5
        AND sum(coalesce(downfunnel.days_visited_web_analytics, 0)) > 3
        AND sum(coalesce(downfunnel.filtered_web_analytics, 0)) > 3
        AND sum(coalesce(downfunnel.first_team_event_ingested, 0)) > 0
),
retained AS (
    SELECT DISTINCT
        e.organization_id,
        showed_intent.start_month
    FROM web_analytics_activation_base_events AS e
    JOIN showed_intent ON e.organization_id = showed_intent.organization_id
    JOIN successful_orgs ON e.organization_id = successful_orgs.organization_id
    WHERE e.event_date >= showed_intent.start_date + toIntervalMonth(3)
        AND e.event_date <= showed_intent.start_date + toIntervalMonth(4)
        AND e.event = '$pageview'
        AND match(e.current_url, 'https://(app|eu|us)\\\\.posthog\\\\.com/project/\\\\d+/web.*')
),
retention_stats AS (
    SELECT
        showed_intent.start_month,
        count(DISTINCT retained.organization_id) AS retained_count,
        count(DISTINCT successful_orgs.organization_id) AS successful_count
    FROM showed_intent
    LEFT JOIN successful_orgs ON showed_intent.organization_id = successful_orgs.organization_id
    LEFT JOIN retained
        ON showed_intent.organization_id = retained.organization_id
        AND showed_intent.start_month = retained.start_month
    GROUP BY showed_intent.start_month
)
SELECT
    showed_intent.start_month AS start_month,
    count(DISTINCT showed_intent.organization_id) AS total_starts,
    count(DISTINCT event_sent_orgs.organization_id) AS events_sent,
    count(DISTINCT successful_orgs.organization_id) AS total_orgs_activated,
    round(
        count(DISTINCT successful_orgs.organization_id) * 100.0
        / nullif(count(DISTINCT showed_intent.organization_id), 0),
        2
    ) AS activation_percentage,
    any(r.retained_count) AS total_activated_orgs_survived,
    round(any(r.retained_count) * 100.0 / nullif(any(r.successful_count), 0), 2) AS retained_percentage_of_activated
FROM showed_intent
LEFT JOIN event_sent_orgs ON showed_intent.organization_id = event_sent_orgs.organization_id
LEFT JOIN successful_orgs ON showed_intent.organization_id = successful_orgs.organization_id
LEFT JOIN retention_stats AS r ON showed_intent.start_month = r.start_month
GROUP BY showed_intent.start_month
ORDER BY showed_intent.start_month
""".strip()


# ----------------------------------------------------------------------------
# Synthetic event generation
# ----------------------------------------------------------------------------


def _wa_url(rng: random.Random, *, with_filter: bool) -> str:
    """URL that the activation regex picks up as a web-analytics visit."""
    host = rng.choice(["app", "eu", "us"])
    project_id = rng.randint(100, 999)
    suffix = "?filter_test_account=true" if with_filter else ""
    return f"https://{host}.posthog.com/project/{project_id}/web{suffix}"


def _noise_url(rng: random.Random) -> str:
    """Non-web-analytics URL — included so the matview's `LIKE '%/web%'` filter
    actually filters something (otherwise it looks trivially passable).
    """
    host = rng.choice(["app", "eu", "us"])
    project_id = rng.randint(100, 999)
    page = rng.choice(["/insights", "/dashboard", "/events", "/persons", "/settings", "/feature_flags"])
    return f"https://{host}.posthog.com/project/{project_id}{page}"


def _person_uuid_for(team_id: int, org_id: str) -> str:
    return str(uuid_module.uuid5(WA_DEMO_NAMESPACE, f"person:{team_id}:{org_id}"))


def _event_uuid_for(team_id: int, org_id: str, seq: int) -> uuid_module.UUID:
    return uuid_module.uuid5(WA_DEMO_NAMESPACE, f"event:{team_id}:{org_id}:{seq}")


def _intent_event(rng: random.Random) -> str:
    return rng.choices(["user showed product intent", "onboarding product selected"], weights=[70, 30])[0]


def _person_properties(org_id: str, *, internal: bool = False) -> dict[str, Any]:
    if internal:
        return {
            "organization_id": "posthog_internal",
            "email": "someone@posthog.com",
            "realm": "cloud",
            "product_key": "web_analytics",
        }
    return {
        "organization_id": org_id,
        "email": f"user@{org_id}.example",
        "realm": "cloud",
        "product_key": "web_analytics",
    }


def _event_properties(
    rng: random.Random,
    *,
    event: str,
    is_wa_pageview: bool = False,
    with_filter: bool = False,
    internal: bool = False,
) -> dict[str, Any]:
    """Event-level properties. `realm`, `product_key`, `host` and `$current_url`
    are read directly by the prod materialized view.
    """
    realm = "cloud"
    product_key = "web_analytics"
    host = "localhost:8010" if internal else "app.posthog.com"
    props: dict[str, Any] = {"realm": realm, "product_key": product_key, "host": host}
    if event == "$pageview":
        if is_wa_pageview:
            props["$current_url"] = _wa_url(rng, with_filter=with_filter)
        else:
            props["$current_url"] = _noise_url(rng)
    return props


def _journey_for_outcome(
    rng: random.Random, intent_date: datetime, outcome: str, now: datetime
) -> list[tuple[datetime, str, dict[str, Any]]]:
    """Yield (timestamp, event_name, event_properties) for one org's full journey.

    Bucket shapes are chosen so the final cohort funnel produces a realistic
    distribution (~35% activation, ~50% retention of activated) while pushing
    total event volume above ~10k across the default 200-org seed.
    """
    journey: list[tuple[datetime, str, dict[str, Any]]] = []

    journey.append((intent_date, _intent_event(rng), _event_properties(rng, event="user showed product intent")))

    if outcome == "never":
        return journey

    # First-team-event ingested — 1-7 days after intent
    journey.append(
        (
            intent_date + timedelta(days=rng.randint(1, 7)),
            "first team event ingested",
            _event_properties(rng, event="first team event ingested"),
        )
    )

    # Per-bucket activity inside the 30-day window
    if outcome == "events_only":
        n_wa, distinct_days, n_filter, n_noise = 0, 0, 0, rng.randint(2, 5)
    elif outcome == "partial":
        n_wa, distinct_days, n_filter, n_noise = (
            rng.randint(1, 3),
            rng.randint(1, 2),
            rng.randint(0, 1),
            rng.randint(8, 15),
        )
    elif outcome in {"activated", "retained"}:
        n_wa, distinct_days, n_filter, n_noise = (
            rng.randint(8, 14),
            rng.randint(4, 7),
            rng.randint(4, 6),
            rng.randint(30, 60),
        )
    else:
        raise ValueError(f"Unknown outcome: {outcome}")

    # Distinct days on which the org visited web analytics
    wa_days = rng.sample(range(1, 30), k=distinct_days) if distinct_days else []
    per_wa_day = max(1, n_wa // max(distinct_days, 1)) if distinct_days else 0

    for day_offset in wa_days:
        for _ in range(per_wa_day):
            ts = intent_date + timedelta(days=day_offset, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
            journey.append((ts, "$pageview", _event_properties(rng, event="$pageview", is_wa_pageview=True)))

    # Filter clicks (a /web URL with `filter` in it)
    for _ in range(n_filter):
        day_offset = rng.choice(wa_days) if wa_days else rng.randint(1, 30)
        ts = intent_date + timedelta(days=day_offset, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
        journey.append(
            (ts, "$pageview", _event_properties(rng, event="$pageview", is_wa_pageview=True, with_filter=True))
        )

    # Background pageviews on non-/web pages — gives the matview's URL filter teeth.
    for _ in range(n_noise):
        ts = intent_date + timedelta(days=rng.randint(0, 30), hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
        journey.append((ts, "$pageview", _event_properties(rng, event="$pageview", is_wa_pageview=False)))

    # Occasional engagement events — irrelevant to activation but realistic.
    if rng.random() < 0.5:
        journey.append(
            (
                intent_date + timedelta(days=rng.randint(2, 20)),
                "team member invited",
                _event_properties(rng, event="team member invited"),
            )
        )
    if rng.random() < 0.3:
        journey.append(
            (
                intent_date + timedelta(days=rng.randint(5, 25)),
                "billing subscription activated",
                _event_properties(rng, event="billing subscription activated"),
            )
        )

    # Retention window: 3-4 months after intent. Emit any retention events that
    # have already happened by `now` (intent + 90d ≤ now). Clipping the upper
    # bound at `now` is what lets newer cohorts still show some retention without
    # waiting the full 30-day window.
    if outcome == "retained":
        retention_start = intent_date + timedelta(days=90)
        retention_end = min(intent_date + timedelta(days=120), now)
        if retention_start <= now:
            day_span = max(0, (retention_end - retention_start).days)
            for _ in range(rng.randint(2, 4)):
                ts = retention_start + timedelta(days=rng.randint(0, day_span), hours=rng.randint(0, 23))
                journey.append((ts, "$pageview", _event_properties(rng, event="$pageview", is_wa_pageview=True)))

    return journey


# ----------------------------------------------------------------------------
# ClickHouse writes
# ----------------------------------------------------------------------------


def _write_person(team_id: int, *, person_uuid: str, properties: dict[str, Any], created_at: datetime) -> None:
    """Create the Person + PersonDistinctId rows in ClickHouse. Idempotent under
    the same UUID — re-runs replay the same Kafka message and ClickHouse dedupes.
    """
    create_person(team_id=team_id, version=0, uuid=person_uuid, properties=properties, created_at=created_at)


def _seed_one_org(
    *,
    team: Team,
    org_id: str,
    outcome: str,
    intent_date: datetime,
    rng: random.Random,
    now: datetime,
    internal: bool = False,
) -> int:
    """Emit one org's worth of persons + events. Returns event count."""
    person_uuid = _person_uuid_for(team.pk, org_id)
    distinct_id = f"distinct_{org_id}"
    person_props = _person_properties(org_id, internal=internal)

    _write_person(team.pk, person_uuid=person_uuid, properties=person_props, created_at=intent_date)
    create_person_distinct_id(team_id=team.pk, distinct_id=distinct_id, person_id=person_uuid)

    journey = _journey_for_outcome(rng, intent_date, outcome, now=now)

    for seq, (ts, event_name, event_props) in enumerate(journey):
        if internal:
            # Override only the bits the matview's filter actually keys on
            event_props = {**event_props, "host": "localhost:8010"}
        create_event(
            event_uuid=_event_uuid_for(team.pk, org_id, seq),
            event=event_name,
            team=team,
            distinct_id=distinct_id,
            timestamp=ts,
            properties=event_props,
            person_id=uuid_module.UUID(person_uuid),
            person_properties=person_props,
            person_created_at=intent_date,
        )
    return len(journey)


# ----------------------------------------------------------------------------
# Upsert helpers — same shape as arr_demo.py
# ----------------------------------------------------------------------------


def _saved_query_columns(types: dict[str, str]) -> dict[str, dict[str, str | bool]]:
    out: dict[str, dict[str, str | bool]] = {}
    for col, ch_type in types.items():
        base = clean_type(ch_type)
        out[col] = {
            "hogql": CLICKHOUSE_HOGQL_MAPPING[base].__name__,
            "clickhouse": ch_type,
            "valid": True,
        }
    return out


def _upsert(manager: Any, *, lookup: dict[str, Any], defaults: dict[str, Any]) -> Any:
    try:
        obj = manager.get(**lookup)
        for field, value in defaults.items():
            setattr(obj, field, value)
        obj.save()
        return obj
    except manager.model.DoesNotExist:
        return manager.create(**lookup, **defaults)


def _upsert_saved_query(*, team: Team, name: str, query: str, columns: dict[str, str]) -> DataWarehouseSavedQuery:
    return _upsert(
        DataWarehouseSavedQuery.objects,
        lookup={"team": team, "name": name},
        defaults={
            "query": {"kind": "HogQLQuery", "query": query},
            "columns": _saved_query_columns(columns),
            "status": DataWarehouseSavedQuery.Status.COMPLETED,
            "latest_error": None,
            "is_materialized": False,
            "deleted": False,
        },
    )


def _upsert_insight(*, team: Team, name: str, description: str, hogql: str) -> Insight:
    return _upsert(
        Insight.objects,
        lookup={"team": team, "name": name},
        defaults={
            "description": description,
            "query": {
                "kind": "DataVisualizationNode",
                "source": {"kind": "HogQLQuery", "query": hogql},
            },
            "saved": True,
            "deleted": False,
            "filters": {},
        },
    )


# ----------------------------------------------------------------------------
# Entry point — called from HedgeboxMatrix._set_up_demo_data_warehouse_tables
# ----------------------------------------------------------------------------


def seed_wa_activation_demo(
    matrix: HedgeboxMatrix, team: Team, user: User, credential: DataWarehouseCredential, n_orgs: int = 400
) -> None:
    """Seed events + persons + saved query + insight for the WA activation demo.

    The `credential` arg is kept for signature compatibility with arr_demo so
    the matrix can call both with the same arguments — it's unused here since
    nothing writes to MinIO.
    """
    rng = random.Random(WA_DEMO_RANDOM_SEED)
    now = matrix.now

    # Stale-row cleanup: prior versions wrote `web_analytics_activation_base_events`
    # as a warehouse table — that would shadow the saved query we're about to create.
    DataWarehouseTable.raw_objects.filter(team=team, name="web_analytics_activation_base_events", deleted=False).update(
        deleted=True
    )

    # Stale-events cleanup: re-running with code changes produces a different
    # journey shape and thus different event UUIDs. Without this, ClickHouse keeps
    # both sets and the funnel double-counts everything.
    tag_queries(product="warehouse", feature="management_command")
    sync_execute(
        f"""
        ALTER TABLE {EVENTS_DATA_TABLE()} {ON_CLUSTER_CLAUSE()} DELETE
        WHERE team_id = %(team_id)s
          AND (distinct_id LIKE 'distinct_org_demo_%%' OR distinct_id LIKE 'distinct_posthog_internal_%%')
        """,
        {"team_id": team.pk},
    )

    # Intent dates spread across the matview's 4-month window. Anchor 4 months
    # ago, leave a 5-day buffer before `now`.
    earliest_intent = now - timedelta(days=120)
    intent_span_days = 120 - 5

    outcomes = rng.choices(
        list(OUTCOME_WEIGHTS.keys()),
        weights=list(OUTCOME_WEIGHTS.values()),
        k=n_orgs,
    )

    total_events = 0
    for i, outcome in enumerate(outcomes, start=1):
        org_id = f"org_demo_{i:04d}"
        # Bias `retained` orgs toward the first 30 days of the window so retention
        # (intent + 90-120 days) has a chance to fully materialize before `now`.
        if outcome == "retained":
            intent_offset_days = rng.randint(0, 30)
        else:
            intent_offset_days = rng.randint(0, intent_span_days)
        intent_date = earliest_intent + timedelta(
            days=intent_offset_days,
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        total_events += _seed_one_org(
            team=team, org_id=org_id, outcome=outcome, intent_date=intent_date, rng=rng, now=now
        )

    # Internal posthog.com users — the matview filter should exclude them.
    # If it ever breaks, the cohort numbers drift visibly. 10 orgs, light traffic.
    for i in range(1, 11):
        org_id = f"posthog_internal_{i:02d}"
        intent_date = earliest_intent + timedelta(days=rng.randint(0, intent_span_days))
        total_events += _seed_one_org(
            team=team,
            org_id=org_id,
            outcome=rng.choice(["activated", "partial"]),
            intent_date=intent_date,
            rng=rng,
            now=now,
            internal=True,
        )

    _upsert_saved_query(
        team=team,
        name="web_analytics_activation_base_events",
        query=MATERIALIZED_VIEW_SQL,
        columns=MATERIALIZED_VIEW_OUTPUT_COLUMNS,
    )

    _upsert_insight(
        team=team,
        name=INSIGHT_NAME,
        description=INSIGHT_DESCRIPTION,
        hogql=ACTIVATION_FUNNEL_SQL,
    )

    # `total_events` is computed but not surfaced — the wrapper command and
    # MatrixManager both already report their own progress.
    _ = total_events
