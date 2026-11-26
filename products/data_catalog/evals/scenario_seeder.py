"""Seeder hooks that write the analysis scenario pack into a per-case team.

The seeder contract takes no per-case parameters, so each combination of needles has its own
function. Seeders only add rows: planted persons carry the ``evalpack`` token in their distinct
ids and emails, and nothing the Hedgebox simulation wrote is changed or removed.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from django.utils import timezone

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.models.event.util import bulk_create_events
from posthog.models.group import Group
from posthog.models.group.util import get_groups_by_identifiers, raw_create_group_ch
from posthog.models.person import Person
from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2, INSERT_PERSON_BULK_SQL
from posthog.models.person.util import get_persons_mapped_by_distinct_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.persons_db import persons_db_connection
from posthog.persons_seed import insert_seed_distinct_id, insert_seed_group, insert_seed_person

from products.annotations.backend.facade.api import create_project_annotation
from products.data_catalog.backend.facade.api import approve_metric, upsert_metric
from products.data_catalog.evals.catalog_seeders import (
    seed_catalog_for_account_check_in,
    seed_catalog_for_account_spend,
    seed_catalog_noise_only,
    seed_catalog_with_early_downgrades,
    seed_catalog_with_new_signups,
    seed_operations_catalog,
)
from products.data_catalog.evals.catalog_synthesizer import TOOL_FAILURE_RATE_METRIC
from products.data_catalog.evals.scenario_synthesizer import (
    CAMPAIGN_ANNOTATION_CONTENT,
    CAMPAIGN_ANNOTATION_DAYS_AGO,
    CAMPAIGN_PATH,
    CAMPAIGN_UTM_SOURCE,
    MCP_EXPORT_FIRST_SEEN_DAYS_AGO,
    MCP_EXPORT_TOOL,
    MCP_FAILING_TOOL,
    MCP_FAILURE_RISE_DAYS,
    MCP_SHARE_TOOL,
    ORG_GRAIN_METRIC_DEFINITION,
    ORG_GRAIN_METRIC_DESCRIPTION,
    ORG_GRAIN_METRIC_NAME,
    POST_TAX_MULTIPLIER,
    PREVIEW_ADOPTION,
    PREVIEW_LAUNCH,
    PREVIEW_RENDER_ERROR_TYPE,
    PREVIEW_RENDER_ERROR_VALUE,
    PREVIEW_RENDER_FINGERPRINT,
    PREVIEW_RENDER_FUNCTION,
    PREVIEW_RENDER_ISSUE_DESCRIPTION,
    PREVIEW_RENDER_ISSUE_NAME,
    PREVIEW_RENDER_SOURCE,
    PREVIEW_RENDER_URL,
    SHARE_BLOCK_FROM_DAYS_AGO,
    SHARE_DAU_DAILY_SHARERS,
    SHARE_DAU_WINDOW_DAYS,
    SHARE_EXPOSURE_TO_DAYS_AGO,
    SHARE_FLAG_BLOCKED_VARIANT,
    SHARE_FLAG_CONTROL_VARIANT,
    SLACK_PRETAX_TEXT,
    UPGRADE_BANNER_EXPERIMENT_NAME,
    UPGRADE_BANNER_METRIC,
    UPGRADE_BANNER_START_DAYS_AGO,
    UPLOAD_DOUBLE_COUNT,
    WAU_BOT_BROWSER,
    WAU_SPIKE_DAYS_AGO,
    AccountNeedle,
    AdoptionSpec,
    EventNeedle,
    FlagNeedle,
    TableNeedle,
    build_expansion_account,
    build_flat_wau,
    build_mcp_tool_failures,
    build_mcp_tool_shipped,
    build_renewal_account,
    build_revenue_rep_outlier,
    build_share_dau,
    build_share_drop_flag,
    build_slack_export,
    build_upgrade_banner,
    build_wau_bot_spike,
    build_wau_spike,
    crm_deals_table,
    initial_person_properties,
    stable_share,
)
from products.data_catalog.evals.seeders import (
    FLOAT_COLUMN,
    STRING_COLUMN,
    synced_table,
    synced_table_names,
    team_and_user,
)
from products.error_tracking.backend.facade.api import list_issues, resolve_fingerprints
from products.error_tracking.backend.facade.testing import (
    create_issue,
    create_issue_fingerprint,
    sync_issue_to_clickhouse,
)
from products.experiments.backend.facade.api import create_experiment
from products.experiments.backend.facade.contracts import CreateExperimentInput
from products.feature_flags.backend.facade.api import create_flag
from products.posthog_ai.evals.error_tracking.seeders import _build_exception_properties
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

if TYPE_CHECKING:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

__all__ = [
    "seed_expansion_account_in_catalog",
    "seed_flat_wau",
    "seed_health_check_mix",
    "seed_mcp_tool_shipped",
    "seed_org_grain_metric",
    "seed_preview_adoption",
    "seed_preview_launch_in_catalog",
    "seed_renewal_account_in_catalog",
    "seed_revenue_rep_outlier",
    "seed_share_dau",
    "seed_share_drop_flag",
    "seed_slack_pretax_note",
    "seed_upgrade_banner_in_catalog",
    "seed_upload_double_count",
    "seed_wau_bot_spike",
    "seed_wau_spike_with_annotation",
]

# Hedgebox registers the account group type first.
_ACCOUNT_GROUP_TYPE_INDEX: Final = 0

# Agents count active users from page views, often with the file events added, so the planted share uses both.
_PREVIEW_ACTIVITY_EVENTS = ("$pageview", "logged_in", "uploaded_file", "downloaded_file", "shared_file_link")

_CRM_COLUMN_TYPES = {
    "deal_id": STRING_COLUMN,
    "rep_name": STRING_COLUMN,
    "rep_email": STRING_COLUMN,
    "account_name": STRING_COLUMN,
    "closed_on": STRING_COLUMN,
    "amount_usd": FLOAT_COLUMN,
}
_SLACK_COLUMN_TYPES = dict.fromkeys(("channel", "ts", "user", "text"), STRING_COLUMN)
_TABLE_DESCRIPTIONS = {
    "crm_deals": "CRM export of closed deals, one row per deal, amounts in USD.",
    "slack_messages": "Export of internal Slack messages from the team's public channels.",
}


def _person_uuid(team_id: int, distinct_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{team_id}:{distinct_id}")


def _at(now: datetime, days_ago: int, minute_of_day: int = 720) -> datetime:
    day_start = (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    return day_start + timedelta(minutes=minute_of_day)


# Rows per bulk insert, so a large needle does not build one huge statement.
_PERSON_INSERT_BATCH = 1_000
# bulk_create_events copies its parameters on every row, so one large call takes quadratic time.
_EVENT_INSERT_BATCH = 1_000


def _clickhouse_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")


def _insert_clickhouse_persons(
    team: Team,
    needle: EventNeedle,
    person_properties: dict[str, dict[str, Any]],
    *,
    created_at: datetime,
    last_seen: datetime,
) -> None:
    """Write the needle's persons and distinct ids to ClickHouse in a few bulk inserts, not two inserts per person."""
    for offset in range(0, len(needle.persons), _PERSON_INSERT_BATCH):
        params: dict[str, Any] = {
            "team": team.id,
            "created_at": _clickhouse_time(created_at),
            "last_seen": _clickhouse_time(last_seen),
        }
        person_values: list[str] = []
        distinct_id_values: list[str] = []
        for index, person in enumerate(needle.persons[offset : offset + _PERSON_INSERT_BATCH]):
            params.update(
                {
                    f"id{index}": str(_person_uuid(team.id, person.distinct_id)),
                    f"distinct{index}": person.distinct_id,
                    f"props{index}": json.dumps(person_properties[person.distinct_id]),
                    f"identified{index}": int(bool(person.email)),
                }
            )
            person_values.append(
                f"(%(id{index})s, %(created_at)s, %(team)s, %(props{index})s, %(identified{index})s, now(), 0, 0, 0, "
                "%(last_seen)s)"
            )
            distinct_id_values.append(f"(%(distinct{index})s, %(id{index})s, %(team)s, 0, 0, now(), 0, 0)")
        sync_execute(
            INSERT_PERSON_BULK_SQL + ",".join(person_values), params, workload=Workload.OFFLINE, team_id=team.id
        )
        sync_execute(
            BULK_INSERT_PERSON_DISTINCT_ID2 + ",".join(distinct_id_values),
            params,
            workload=Workload.OFFLINE,
            team_id=team.id,
        )


def _plant_needle(team: Team, needle: EventNeedle, now: datetime) -> int:
    """Create the needle's persons in ClickHouse and the persons database, then write its events."""
    first_seen = min((_at(now, event.days_ago, event.minute_of_day) for event in needle.events), default=now)
    last_seen = max((_at(now, event.days_ago, event.minute_of_day) for event in needle.events), default=now)
    created_at = first_seen - timedelta(minutes=5)
    person_properties: dict[str, dict[str, Any]] = {}
    initial_properties = initial_person_properties(needle.events)
    # Personhog serves person lookups from the persons database, so a person that exists only in
    # ClickHouse could not be hydrated by an id lookup the agent makes.
    with persons_db_connection(writer=True, autocommit=True) as conn:
        for person in needle.persons:
            properties = initial_properties.get(person.distinct_id, {}) | {
                key: value for key, value in (("email", person.email), ("name", person.name)) if value
            }
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
    person_mapping: dict[str, Person] = {}
    for person in needle.persons:
        person_uuid = str(_person_uuid(team.id, person.distinct_id))
        # Without the mapping, bulk_create_events looks the person up once per event.
        person_mapping[person.distinct_id] = Person(
            team_id=team.id,
            uuid=person_uuid,
            properties=person_properties[person.distinct_id],
            created_at=created_at,
        )
    _insert_clickhouse_persons(team, needle, person_properties, created_at=created_at, last_seen=last_seen)
    _write_events(
        team,
        [
            {
                "event": event.event,
                "team": team,
                "distinct_id": event.distinct_id,
                "timestamp": _at(now, event.days_ago, event.minute_of_day),
                "properties": dict(event.properties),
            }
            for event in needle.events
        ],
        person_mapping,
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
    synced = synced_table(
        team,
        user,
        source_type=ExternalDataSourceType.POSTGRES,
        schema_name=table.schema_name,
        table_name=table.table_name,
        columns={column: column_types[column] for column in table.columns},
        rows=_resolved_rows(table, now),
        descriptions={"": description},
    )
    return {"name": synced.name, "aliases": synced_table_names(table.table_name), "rows": len(table.rows)}


# HogQL returns 100 rows for a query without a LIMIT, and never more than this many.
_MAX_SEED_ROWS = 50_000
# Days count in UTC, because `_at` plants events on UTC days and `today()` uses the team's timezone.
_UTC_DAYS_AGO = "dateDiff('day', toDate(toTimeZone(timestamp, 'UTC')), toDate(toTimeZone(now(), 'UTC')))"


def _all_rows(response: Any, query_name: str) -> list[Any]:
    """The query rows. A full page means rows were cut off, so the seed fails as an infrastructure error."""
    rows = list(response.results or [])
    if len(rows) >= _MAX_SEED_ROWS:
        raise RuntimeError(
            f"The {query_name} seed query hit the {_MAX_SEED_ROWS}-row cap, so the planted truth would be partial."
        )
    return rows


def _write_events(team: Team, events: list[dict[str, Any]], person_mapping: dict[str, Person]) -> None:
    """Write the events in bounded batches, with each person and group resolved once for all of them."""
    group_mapping = _group_mapping(team, events)
    for offset in range(0, len(events), _EVENT_INSERT_BATCH):
        bulk_create_events(
            events[offset : offset + _EVENT_INSERT_BATCH], person_mapping=person_mapping, group_mapping=group_mapping
        )


def _group_mapping(team: Team, events: list[dict[str, Any]]) -> dict[tuple[int, str], Group]:
    """Resolve each ``$group_N`` value once, because ``bulk_create_events`` otherwise looks it up per event."""
    keys: dict[int, set[str]] = {}
    for event in events:
        for key, value in event["properties"].items():
            index = key.removeprefix("$group_")
            if index != key and index.isdigit() and isinstance(value, str):
                keys.setdefault(int(index), set()).add(value)
    return {
        (index, group.group_key): group
        for index, group_keys in keys.items()
        for group in get_groups_by_identifiers(team.id, index, sorted(group_keys))
    }


def _person_mapping(team: Team, distinct_ids: Iterable[str]) -> dict[str, Person]:
    """Resolve each distinct id once, because ``bulk_create_events`` otherwise looks the person up per event."""
    return get_persons_mapped_by_distinct_id(team.id, sorted(set(distinct_ids)))


def _plant_flat_wau(team: Team, user: User, now: datetime) -> dict[str, Any]:
    """Hold weekly active users level, so the only WAU change in a case is the one the case plants."""
    response = execute_hogql_query(
        f"SELECT person_id, groupUniqArray({_UTC_DAYS_AGO}) FROM events GROUP BY person_id LIMIT {_MAX_SEED_ROWS}",
        team=team,
        user=user,
    )
    rows = _all_rows(response, "flat WAU")
    if not rows:
        raise RuntimeError("The Hedgebox master data has no events to hold level.")
    daily_active: list[set[str]] = [set() for _ in range(max(max(days) for _, days in rows) + 1)]
    for person_id, days in rows:
        for day in days:
            if day >= 0:
                daily_active[day].add(str(person_id))
    needle = build_flat_wau(daily_active, now.hour * 60 + now.minute)
    _plant_needle(team, needle, now)
    return {"members": len(needle.persons), "events": len(needle.events)}


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
        f"ORDER BY timestamp LIMIT {_MAX_SEED_ROWS}",
        team=team,
        user=user,
        placeholders={
            "event": ast.Constant(value=spec.event),
            "from_days": ast.Constant(value=spec.from_days_ago),
            "to_days": ast.Constant(value=spec.to_days_ago),
        },
    )
    rows = _all_rows(response, "upload doubling")
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
    _write_events(team, events, _person_mapping(team, (event["distinct_id"] for event in events)))
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
        "exposure_to_days_ago": SHARE_EXPOSURE_TO_DAYS_AGO,
    }


def seed_flat_wau(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    return {"flat_wau": _plant_flat_wau(team, user, timezone.now())}


def seed_wau_spike_with_annotation(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    now = timezone.now()
    return {"flat_wau": _plant_flat_wau(team, user, now), "wau_spike": _plant_wau_spike(team, user, now)}


def seed_wau_bot_spike(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    now = timezone.now()
    flat = _plant_flat_wau(team, user, now)
    needle = build_wau_bot_spike()
    events = _plant_needle(team, needle, now)
    return {
        "flat_wau": flat,
        "wau_bot_spike": {"distinct_ids": len(needle.persons), "pageviews": events, "browser": WAU_BOT_BROWSER},
    }


def seed_upload_double_count(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    return {"upload_double_count": _plant_upload_double_count(team, user, timezone.now())}


def seed_share_dau(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, _ = team_and_user(context)
    events = _plant_needle(team, build_share_dau(), timezone.now())
    return {"share_dau": {"daily_sharers": SHARE_DAU_DAILY_SHARERS, "days": SHARE_DAU_WINDOW_DAYS, "events": events}}


def seed_share_drop_flag(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    return {"share_drop_flag": _plant_share_drop_flag(team, user, timezone.now())}


def seed_health_check_mix(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    now = timezone.now()
    return {
        "flat_wau": _plant_flat_wau(team, user, now),
        "wau_spike": _plant_wau_spike(team, user, now),
        "upload_double_count": _plant_upload_double_count(team, user, now),
        "share_drop_flag": _plant_share_drop_flag(team, user, now),
    }


def seed_revenue_rep_outlier(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
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


@frozen
class _PreviewAdopter:
    distinct_id: str
    person_id: Any
    days_ago: int


def _preview_adopters(team: Team, user: User, spec: AdoptionSpec) -> list[_PreviewAdopter]:
    """Each active day of each user who previews a file on that day."""
    response = execute_hogql_query(
        f"SELECT distinct_id, any(person_id), {_UTC_DAYS_AGO} AS days_ago FROM events "
        # The timestamp bound only prunes the scan, so the time of day cannot change the result.
        f"WHERE event IN {{events}} AND timestamp >= now() - toIntervalDay({{days}} + 2) AND {_UTC_DAYS_AGO} <= {{days}} "
        f"GROUP BY distinct_id, days_ago ORDER BY days_ago, distinct_id LIMIT {_MAX_SEED_ROWS}",
        team=team,
        user=user,
        placeholders={
            "events": ast.Tuple(exprs=[ast.Constant(value=event) for event in _PREVIEW_ACTIVITY_EVENTS]),
            "days": ast.Constant(value=spec.first_seen_days_ago),
        },
    )
    active_by_day: dict[int, list[tuple[str, Any]]] = {}
    for distinct_id, person_id, days_ago in _all_rows(response, "preview adoption"):
        if 1 <= days_ago <= spec.first_seen_days_ago:
            active_by_day.setdefault(int(days_ago), []).append((distinct_id, person_id))
    if spec.first_seen_days_ago not in active_by_day:
        raise RuntimeError("No active users on the preview launch day; the Hedgebox master data is too old.")
    # A user adopts once the day's share passes the user's fixed hash value, and previews on every
    # active day after that. Then a daily and a weekly share of active users both end near the end share.
    return [
        _PreviewAdopter(distinct_id=distinct_id, person_id=person_id, days_ago=days_ago)
        for days_ago, users in active_by_day.items()
        for distinct_id, person_id in users
        if stable_share(distinct_id) < spec.share_on(days_ago)
    ]


def _preview_event(
    team: Team, now: datetime, spec: AdoptionSpec, adopter: _PreviewAdopter, file_type: str
) -> dict[str, Any]:
    return {
        "event": spec.event,
        "team": team,
        "distinct_id": adopter.distinct_id,
        "timestamp": _at(now, adopter.days_ago, 780),
        "properties": {"file_type": file_type, "file_size_b": 1_048_576},
        "person_id": adopter.person_id,
    }


def seed_preview_adoption(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    spec = PREVIEW_ADOPTION
    now = timezone.now()
    events = [
        _preview_event(team, now, spec, adopter, "application/pdf") for adopter in _preview_adopters(team, user, spec)
    ]
    _write_events(team, events, _person_mapping(team, (event["distinct_id"] for event in events)))
    return {
        "preview_adoption": {
            "event": spec.event,
            "first_seen_days_ago": spec.first_seen_days_ago,
            "start_share": spec.start_share,
            "end_share": spec.end_share,
            "events": len(events),
        }
    }


@frozen
class _IssueFingerprint:
    issue_id: str
    fingerprint: str


def _preview_render_issue(team: Team, now: datetime) -> _IssueFingerprint:
    """The Hedgebox preview render issue of the case team. A team without it gets the issue from the seed."""
    issue = next((issue for issue in list_issues(team.id) if issue.name == PREVIEW_RENDER_ISSUE_NAME), None)
    if issue is not None:
        fingerprints = resolve_fingerprints(team.id, [str(issue.id)])
        if fingerprints:
            return _IssueFingerprint(issue_id=str(issue.id), fingerprint=fingerprints[0])
    first_seen = _at(now, PREVIEW_LAUNCH.adoption.first_seen_days_ago, 0)
    issue_id = (
        issue.id
        if issue is not None
        else create_issue(
            team_id=team.id,
            name=PREVIEW_RENDER_ISSUE_NAME,
            description=PREVIEW_RENDER_ISSUE_DESCRIPTION,
            created_at=first_seen,
        )
    )
    create_issue_fingerprint(
        team_id=team.id, issue_id=issue_id, fingerprint=PREVIEW_RENDER_FINGERPRINT, first_seen=first_seen
    )
    sync_issue_to_clickhouse(team_id=team.id, issue_id=issue_id)
    return _IssueFingerprint(issue_id=str(issue_id), fingerprint=PREVIEW_RENDER_FINGERPRINT)


def _plant_preview_launch(team: Team, user: User, now: datetime) -> dict[str, Any]:
    spec = PREVIEW_LAUNCH
    issue = _preview_render_issue(team, now)
    error = {
        "url": PREVIEW_RENDER_URL,
        "fingerprint": issue.fingerprint,
        "type": PREVIEW_RENDER_ERROR_TYPE,
        "value": PREVIEW_RENDER_ERROR_VALUE,
        "source": PREVIEW_RENDER_SOURCE,
        "function": PREVIEW_RENDER_FUNCTION,
    }
    previews: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for adopter in _preview_adopters(team, user, spec.adoption):
        preview = _preview_event(
            team, now, spec.adoption, adopter, spec.file_type_for(adopter.distinct_id, adopter.days_ago)
        )
        previews.append(preview)
        if spec.fails(adopter.distinct_id, adopter.days_ago):
            errors.append(
                {
                    "event": "$exception",
                    "team": team,
                    "distinct_id": adopter.distinct_id,
                    "timestamp": preview["timestamp"] + timedelta(seconds=2),
                    "properties": _build_exception_properties(error, issue.issue_id, str(uuid.uuid4())),
                    "person_id": adopter.person_id,
                }
            )
    events = previews + errors
    _write_events(team, events, _person_mapping(team, (event["distinct_id"] for event in events)))
    return {
        "event": spec.adoption.event,
        "first_seen_days_ago": spec.adoption.first_seen_days_ago,
        "previews": len(previews),
        "render_errors": len(errors),
        "failing_file_type": spec.failing_file_type,
        "issue_id": issue.issue_id,
    }


def seed_mcp_tool_shipped(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, _ = team_and_user(context)
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


def seed_mcp_tool_failures(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    events = _plant_needle(team, build_mcp_tool_failures(), timezone.now())
    spec = TOOL_FAILURE_RATE_METRIC
    metric = upsert_metric(
        team=team,
        user=user,
        name=spec.name,
        display_name=spec.display_name,
        description=spec.description,
        unit=spec.unit,
        definition=spec.definition,
        overwrite=True,
    )
    approve_metric(metric, user)
    return {
        "mcp_tool_failures": {
            "failing_tool": MCP_FAILING_TOOL,
            "rise_days": MCP_FAILURE_RISE_DAYS,
            "metric": spec.name,
            "events": events,
        }
    }


# The alert cases put the scenario inside the noise catalog, so the agent must pick the fitting metric out of it.
def seed_tool_failures_in_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {**seed_catalog_noise_only(context), **seed_mcp_tool_failures(context)}


def seed_signup_spike_in_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {**seed_catalog_with_new_signups(context), **seed_wau_spike_with_annotation(context)}


def seed_upload_double_count_in_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    return {**seed_catalog_noise_only(context), **seed_upload_double_count(context)}


def seed_slack_pretax_note(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    slack = build_slack_export()
    table = _seed_table(
        team, user, slack.table, _SLACK_COLUMN_TYPES, _TABLE_DESCRIPTIONS["slack_messages"], timezone.now()
    )
    return {"slack_messages": table, "pretax_note": SLACK_PRETAX_TEXT, "post_tax_multiplier": POST_TAX_MULTIPLIER}


def seed_org_grain_metric(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
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


def _plant_account(team: Team, needle: AccountNeedle, now: datetime) -> dict[str, Any]:
    """Create the account group before the members' events, so each event finds the group by its $group_0 key."""
    account = needle.account
    created_at = _at(now, max(event.days_ago for event in needle.members.events), 0) - timedelta(days=1)
    with persons_db_connection(writer=True, autocommit=True) as conn:
        insert_seed_group(
            conn,
            team_id=team.id,
            group_key=account.group_key,
            group_type_index=_ACCOUNT_GROUP_TYPE_INDEX,
            group_properties=account.properties,
            created_at=created_at,
        )
    # The persons database row exists now, so only the ClickHouse row is left. The demo data writes groups the same way.
    raw_create_group_ch(team.id, _ACCOUNT_GROUP_TYPE_INDEX, account.group_key, account.properties, created_at)
    return {
        "name": account.properties["name"],
        "group_key": account.group_key,
        "members": len(needle.members.persons),
        "events": _plant_needle(team, needle.members, now),
    }


def _plant_upgrade_banner(team: Team, user: User, now: datetime) -> dict[str, Any]:
    needle = build_upgrade_banner()
    share = 100 // len(needle.variants)
    experiment = create_experiment(
        team=team,
        user=user,
        input_dto=CreateExperimentInput(
            name=UPGRADE_BANNER_EXPERIMENT_NAME,
            feature_flag_key=needle.key,
            description="Show a banner on the files page that offers the pro plan.",
            feature_flag_config={
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "multivariate": {
                        "variants": [
                            {"key": variant, "name": variant.capitalize(), "rollout_percentage": share}
                            for variant in needle.variants
                        ]
                    },
                }
            },
            # The service stamps a fingerprint on each metric, so it gets a copy of the shared constant.
            metrics=[copy.deepcopy(UPGRADE_BANNER_METRIC)],
            start_date=_at(now, UPGRADE_BANNER_START_DAYS_AGO, 0),
        ),
    )
    return {
        "experiment_id": experiment.id,
        "experiment_name": UPGRADE_BANNER_EXPERIMENT_NAME,
        "flag_key": needle.key,
        "events": _plant_needle(team, needle.events, now),
    }


# The implied-need cases install the catalog next to the scenario, so the context the prompt does not name is one
# catalog search away.
def seed_renewal_account_in_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, _ = team_and_user(context)
    account = _plant_account(team, build_renewal_account(), timezone.now())
    return {**seed_catalog_for_account_check_in(context), "renewal_account": account}


def seed_expansion_account_in_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, _ = team_and_user(context)
    account = _plant_account(team, build_expansion_account(), timezone.now())
    return {**seed_catalog_for_account_spend(context), "expansion_account": account}


def seed_preview_launch_in_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    launch = _plant_preview_launch(team, user, timezone.now())
    return {**seed_operations_catalog(context), "preview_launch": launch}


def seed_upgrade_banner_in_catalog(context: CustomPromptSandboxContext) -> dict[str, Any]:
    team, user = team_and_user(context)
    banner = _plant_upgrade_banner(team, user, timezone.now())
    return {**seed_catalog_with_early_downgrades(context), "upgrade_banner": banner}
