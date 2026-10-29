"""Seeder hooks that write the analysis scenario pack into a per-case team.

The seeder contract takes no per-case parameters, so each combination of needles has its own
function. Seeders only add rows: planted persons carry the ``evalpack`` token in their distinct
ids and emails, and nothing the Hedgebox simulation wrote is changed or removed.
"""

from __future__ import annotations

import json
import math
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.event.util import bulk_create_events
from posthog.models.person.util import create_person, create_person_distinct_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_distinct_id, insert_seed_person

from products.annotations.backend.facade.api import create_project_annotation
from products.data_catalog.backend.facade.api import approve_metric, upsert_metric
from products.data_catalog.evals.scenario_synthesizer import (
    CAMPAIGN_ANNOTATION_CONTENT,
    CAMPAIGN_ANNOTATION_DAYS_AGO,
    CAMPAIGN_PATH,
    CAMPAIGN_UTM_SOURCE,
    MCP_EXPORT_FIRST_SEEN_DAYS_AGO,
    MCP_EXPORT_TOOL,
    MCP_SHARE_TOOL,
    ORG_GRAIN_METRIC_DEFINITION,
    ORG_GRAIN_METRIC_DESCRIPTION,
    ORG_GRAIN_METRIC_NAME,
    POST_TAX_MULTIPLIER,
    PREVIEW_ADOPTION,
    SHARE_BLOCK_FROM_DAYS_AGO,
    SHARE_BLOCK_TO_DAYS_AGO,
    SHARE_FLAG_BLOCKED_VARIANT,
    SHARE_FLAG_CONTROL_VARIANT,
    SLACK_PRETAX_TEXT,
    UPLOAD_DOUBLE_COUNT,
    WAU_BOT_BROWSER,
    WAU_SPIKE_DAYS_AGO,
    EventNeedle,
    FlagNeedle,
    TableNeedle,
    build_account_health,
    build_mcp_tool_shipped,
    build_revenue_rep_outlier,
    build_share_drop_flag,
    build_slack_export,
    build_wau_bot_spike,
    build_wau_spike,
    crm_deals_table,
)
from products.data_catalog.evals.seeders import _FLOAT_COLUMN, _INTEGER_COLUMN, _STRING_COLUMN, _synced_table
from products.feature_flags.backend.facade.api import create_flag
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

__all__ = [
    "seed_churn_risk_sources",
    "seed_health_check_mix",
    "seed_mcp_tool_shipped",
    "seed_org_grain_metric",
    "seed_preview_adoption",
    "seed_revenue_rep_outlier",
    "seed_share_drop_flag",
    "seed_slack_pretax_note",
    "seed_upload_double_count",
    "seed_wau_bot_spike",
    "seed_wau_spike_with_annotation",
]

_PREVIEW_ACTIVITY_EVENTS = ("logged_in", "uploaded_file", "downloaded_file", "shared_file_link")

_CRM_COLUMN_TYPES = {
    "deal_id": _STRING_COLUMN,
    "rep_name": _STRING_COLUMN,
    "rep_email": _STRING_COLUMN,
    "account_name": _STRING_COLUMN,
    "closed_on": _STRING_COLUMN,
    "amount_usd": _FLOAT_COLUMN,
}
_SLACK_COLUMN_TYPES = dict.fromkeys(("channel", "ts", "user", "text"), _STRING_COLUMN)
_HEALTH_COLUMN_TYPES = {"account_name": _STRING_COLUMN, "churn_health": _INTEGER_COLUMN, "as_of": _STRING_COLUMN}
_TABLE_DESCRIPTIONS = {
    "crm_deals": "CRM export of closed deals, one row per deal, amounts in USD.",
    "slack_messages": "Export of internal Slack messages from the team's public channels.",
    "account_health": "Churn health score per account, from 0 (healthy) to 10 (likely to churn).",
}


def _team_and_user(context: CustomPromptSandboxContext) -> tuple[Team, User]:
    return Team.objects.get(pk=context.team_id), User.objects.get(pk=context.user_id)


def _person_uuid(team_id: int, distinct_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{team_id}:{distinct_id}")


def _at(now: datetime, days_ago: int, minute_of_day: int = 720) -> datetime:
    day_start = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start + timedelta(minutes=minute_of_day)


def _plant_needle(team: Team, needle: EventNeedle, now: datetime) -> int:
    """Create the needle's persons in ClickHouse and the persons database, then write its events."""
    first_seen = min((_at(now, event.days_ago, event.minute_of_day) for event in needle.events), default=now)
    last_seen = max((_at(now, event.days_ago, event.minute_of_day) for event in needle.events), default=now)
    created_at = first_seen - timedelta(minutes=5)
    person_properties: dict[str, dict[str, Any]] = {}
    # Personhog serves person lookups from the persons database, so a person that exists only in
    # ClickHouse could not be hydrated by an id lookup the agent makes.
    with persons_db_connection(writer=True, autocommit=True) as conn:
        for person in needle.persons:
            properties = {key: value for key, value in (("email", person.email), ("name", person.name)) if value}
            person_properties[person.distinct_id] = properties
            person_id = insert_seed_person(
                conn,
                team_id=team.id,
                properties=properties,
                is_identified=bool(person.email),
                uuid=_person_uuid(team.id, person.distinct_id),
                version=0,
                created_at=created_at,
                last_seen_at=last_seen,
            )
            insert_seed_distinct_id(conn, team_id=team.id, person_id=person_id, distinct_id=person.distinct_id)
    for person in needle.persons:
        person_uuid = str(_person_uuid(team.id, person.distinct_id))
        create_person(
            team_id=team.id,
            version=0,
            uuid=person_uuid,
            properties=person_properties[person.distinct_id],
            is_identified=bool(person.email),
            created_at=created_at,
            last_seen_at=last_seen,
        )
        create_person_distinct_id(team_id=team.id, distinct_id=person.distinct_id, person_id=person_uuid)
    bulk_create_events(
        [
            {
                "event": event.event,
                "team": team,
                "distinct_id": event.distinct_id,
                "timestamp": _at(now, event.days_ago, event.minute_of_day),
                "properties": dict(event.properties),
                "person_id": _person_uuid(team.id, event.distinct_id),
                "person_properties": person_properties[event.distinct_id],
            }
            for event in needle.events
        ]
    )
    return len(needle.events)


def _resolved_rows(table: TableNeedle, now: datetime) -> tuple[tuple[Any, ...], ...]:
    if table.date_column is None:
        return table.rows
    index = table.columns.index(table.date_column)
    return tuple(
        (*row[:index], _at(now, row[index]).strftime("%Y-%m-%d %H:%M:%S"), *row[index + 1 :]) for row in table.rows
    )


def _seed_table(
    team: Team, user: User, table: TableNeedle, column_types: dict[str, dict[str, Any]], description: str, now: datetime
) -> dict[str, Any]:
    synced = _synced_table(
        team,
        user,
        source_type=ExternalDataSourceType.POSTGRES,
        schema_name=table.schema_name,
        table_name=table.table_name,
        columns={column: column_types[column] for column in table.columns},
        rows=_resolved_rows(table, now),
        descriptions={"": description},
    )
    return {"name": synced.name, "aliases": table_aliases(table), "rows": len(table.rows)}


def table_aliases(table: TableNeedle) -> list[str]:
    """A synced table answers to its stored name and to the dotted name HogQL builds from the source."""
    return [table.table_name, f"postgres.{table.schema_name}"]


def _plant_wau_spike(team: Team, user: User, now: datetime) -> dict[str, Any]:
    needle = build_wau_spike()
    _plant_needle(team, needle, now)
    create_project_annotation(
        team.id, user.id, content=CAMPAIGN_ANNOTATION_CONTENT, date_marker=_at(now, CAMPAIGN_ANNOTATION_DAYS_AGO, 0)
    )
    return {
        "persons": len(needle.persons),
        "days_ago": list(WAU_SPIKE_DAYS_AGO),
        "landing_path": CAMPAIGN_PATH,
        "utm_source": CAMPAIGN_UTM_SOURCE,
        "annotation": CAMPAIGN_ANNOTATION_CONTENT,
    }


def _plant_upload_double_count(team: Team, user: User, now: datetime) -> dict[str, Any]:
    spec = UPLOAD_DOUBLE_COUNT
    # An explicit LIMIT, because HogQL returns 100 rows for a query without one.
    response = execute_hogql_query(
        "SELECT distinct_id, timestamp, properties, person_id FROM events "
        "WHERE event = {event} AND timestamp >= now() - toIntervalDay({from_days}) "
        "AND timestamp < now() - toIntervalDay({to_days}) "
        "ORDER BY timestamp LIMIT 50000",
        team=team,
        user=user,
        placeholders={
            "event": ast.Constant(value=spec.event),
            "from_days": ast.Constant(value=spec.from_days_ago),
            "to_days": ast.Constant(value=spec.to_days_ago),
        },
    )
    rows = response.results or []
    if not rows:
        # Without uploads in the window there is nothing to double, and the agent would be graded on a
        # tracking bug the data does not show. Fail the seed so the case reads as an infrastructure error.
        raise RuntimeError(f"No {spec.event} events in the duplicate window; the Hedgebox master data is too old.")
    events = []
    for distinct_id, timestamp, properties, person_id in rows:
        duplicated = json.loads(properties) if isinstance(properties, str) else dict(properties or {})
        duplicated["$lib_version"] = spec.lib_version
        events.append(
            {
                "event": spec.event,
                "team": team,
                "distinct_id": distinct_id,
                "timestamp": timestamp,
                "properties": duplicated,
                "person_id": person_id,
            }
        )
    bulk_create_events(events)
    return {
        "event": spec.event,
        "duplicated": len(events),
        "from_days_ago": spec.from_days_ago,
        "to_days_ago": spec.to_days_ago,
        "lib_version": spec.lib_version,
    }


def _plant_share_drop_flag(team: Team, user: User, now: datetime) -> dict[str, Any]:
    needle: FlagNeedle = build_share_drop_flag()
    # A system write (user=None) skips the approval gate, which a seeded team may have no approver for.
    create_flag(
        {
            "key": needle.key,
            "name": "Gate file sharing behind the new permissions check",
            "filters": {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": SHARE_FLAG_CONTROL_VARIANT, "name": "Control", "rollout_percentage": 25},
                        {"key": SHARE_FLAG_BLOCKED_VARIANT, "name": "Blocked", "rollout_percentage": 75},
                    ]
                },
            },
            "active": True,
        },
        team=team,
        user=None,
    )
    _plant_needle(team, needle.events, now)
    return {
        "flag_key": needle.key,
        "blocked_variant": SHARE_FLAG_BLOCKED_VARIANT,
        "from_days_ago": SHARE_BLOCK_FROM_DAYS_AGO,
        "to_days_ago": SHARE_BLOCK_TO_DAYS_AGO,
    }


def seed_wau_spike_with_annotation(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    return {"wau_spike": _plant_wau_spike(team, user, timezone.now())}


def seed_wau_bot_spike(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, _ = _team_and_user(context)
    needle = build_wau_bot_spike()
    events = _plant_needle(team, needle, timezone.now())
    return {"wau_bot_spike": {"distinct_ids": len(needle.persons), "pageviews": events, "browser": WAU_BOT_BROWSER}}


def seed_upload_double_count(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    return {"upload_double_count": _plant_upload_double_count(team, user, timezone.now())}


def seed_share_drop_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    return {"share_drop_flag": _plant_share_drop_flag(team, user, timezone.now())}


def seed_health_check_mix(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    now = timezone.now()
    return {
        "wau_spike": _plant_wau_spike(team, user, now),
        "upload_double_count": _plant_upload_double_count(team, user, now),
        "share_drop_flag": _plant_share_drop_flag(team, user, now),
    }


def seed_revenue_rep_outlier(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    outlier = build_revenue_rep_outlier()
    table = _seed_table(
        team, user, crm_deals_table(outlier), _CRM_COLUMN_TYPES, _TABLE_DESCRIPTIONS["crm_deals"], timezone.now()
    )
    return {
        "crm_deals": table,
        "outlier": {
            "deal_id": outlier.outlier_deal_id,
            "rep": outlier.outlier_rep,
            "top_with_outlier": list(outlier.top_reps_with_outlier),
            "top_without_outlier": list(outlier.top_reps_without_outlier),
        },
    }


def seed_preview_adoption(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    spec = PREVIEW_ADOPTION
    now = timezone.now()
    response = execute_hogql_query(
        "SELECT distinct_id, any(person_id), dateDiff('day', toDate(timestamp), today()) AS days_ago FROM events "
        "WHERE event IN {events} AND timestamp >= now() - toIntervalDay({days}) "
        "GROUP BY distinct_id, days_ago ORDER BY days_ago, distinct_id LIMIT 50000",
        team=team,
        user=user,
        placeholders={
            "events": ast.Tuple(exprs=[ast.Constant(value=event) for event in _PREVIEW_ACTIVITY_EVENTS]),
            "days": ast.Constant(value=spec.first_seen_days_ago),
        },
    )
    active_by_day: dict[int, list[tuple[str, Any]]] = {}
    for distinct_id, person_id, days_ago in response.results or []:
        if 1 <= days_ago <= spec.first_seen_days_ago:
            active_by_day.setdefault(int(days_ago), []).append((distinct_id, person_id))
    if spec.first_seen_days_ago not in active_by_day:
        raise RuntimeError("No active users on the preview launch day; the Hedgebox master data is too old.")
    events = []
    for days_ago, users in active_by_day.items():
        # A stable hash order lets the adopters of one day stay adopters on the next, as real adoption does.
        ranked = sorted(users, key=lambda item: hashlib.sha256(item[0].encode()).hexdigest())
        for distinct_id, person_id in ranked[: math.ceil(spec.share_on(days_ago) * len(ranked))]:
            events.append(
                {
                    "event": spec.event,
                    "team": team,
                    "distinct_id": distinct_id,
                    "timestamp": _at(now, days_ago, 780),
                    "properties": {"file_type": "application/pdf", "file_size_b": 1_048_576},
                    "person_id": person_id,
                }
            )
    bulk_create_events(events)
    return {
        "preview_adoption": {
            "event": spec.event,
            "first_seen_days_ago": spec.first_seen_days_ago,
            "start_share": spec.start_share,
            "end_share": spec.end_share,
            "events": len(events),
        }
    }


def seed_mcp_tool_shipped(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, _ = _team_and_user(context)
    needle = build_mcp_tool_shipped()
    events = _plant_needle(team, needle, timezone.now())
    return {
        "mcp_tool_shipped": {
            "export_tool": MCP_EXPORT_TOOL,
            "share_tool": MCP_SHARE_TOOL,
            "first_seen_days_ago": MCP_EXPORT_FIRST_SEEN_DAYS_AGO,
            "events": events,
        }
    }


def seed_slack_pretax_note(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    slack = build_slack_export()
    table = _seed_table(
        team, user, slack.table, _SLACK_COLUMN_TYPES, _TABLE_DESCRIPTIONS["slack_messages"], timezone.now()
    )
    return {"slack_messages": table, "pretax_note": SLACK_PRETAX_TEXT, "post_tax_multiplier": POST_TAX_MULTIPLIER}


def seed_churn_risk_sources(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Both sources the churn-risk markdown metric reads. The metric itself is the metric-kinds suite's to seed."""
    team, user = _team_and_user(context)
    now = timezone.now()
    slack = build_slack_export()
    health = build_account_health()
    return {
        "slack_messages": _seed_table(
            team, user, slack.table, _SLACK_COLUMN_TYPES, _TABLE_DESCRIPTIONS["slack_messages"], now
        ),
        "account_health": _seed_table(
            team, user, health.table, _HEALTH_COLUMN_TYPES, _TABLE_DESCRIPTIONS["account_health"], now
        ),
        "unhappy_accounts": list(slack.unhappy_accounts),
        "at_risk_accounts": list(health.at_risk_accounts),
    }


def seed_org_grain_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = _team_and_user(context)
    metric = upsert_metric(
        team=team,
        user=user,
        name=ORG_GRAIN_METRIC_NAME,
        description=ORG_GRAIN_METRIC_DESCRIPTION,
        unit="usd",
        definition=ORG_GRAIN_METRIC_DEFINITION,
        overwrite=True,
    )
    approve_metric(metric, user)
    return {"metric": {"name": ORG_GRAIN_METRIC_NAME, "status": "approved", "grain": "account"}}
