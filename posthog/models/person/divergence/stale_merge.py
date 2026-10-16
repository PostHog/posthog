"""Sends a stale person's ClickHouse-only properties to ingestion before Postgres is raised."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from posthog.api.capture import capture_internal
from posthog.models.team import Team

from products.access_control.backend.facade.api import team_has_property_access_rules

from . import datatypes, lookups, repair_plan

# Well under capture's 1,000,000-byte Kafka message limit and ingestion's 655,360-byte person properties limit
# (trimmed to 512 KiB), so ingestion applies the merge whole.
_STALE_MERGE_MAX_BYTES = 256 * 1024

_PERSON_WINNER_PROPERTIES_SQL = """
SELECT argMaxIf(properties, version, _row_exists)
FROM person
WHERE team_id = %(team_id)s AND id = %(person_uuid)s
"""


def _clickhouse_only_properties(plan: repair_plan._PersonPlan) -> dict[str, Any]:
    """The properties of the ClickHouse winner whose keys the Postgres person lacks."""
    assert plan.person is not None
    rows = lookups._ch(
        _PERSON_WINNER_PROPERTIES_SQL,
        {"team_id": plan.team_id, "person_uuid": plan.person_uuid},
        repair_plan._REPAIR_READ_SETTINGS,
    )
    ch_properties = json.loads(rows[0][0]) if rows and rows[0][0] else {}
    pg_properties = plan.person.properties or {}
    return {key: value for key, value in ch_properties.items() if key not in pg_properties}


def _queue_stale_merge(
    plan: repair_plan._PersonPlan, distinct_id: str, missing: dict[str, Any]
) -> datatypes.RepairOutcome | None:
    """Send the ClickHouse-only properties to ingestion as $set_once, or return why they were not sent."""
    assert plan.person is not None
    return send_set_once(
        plan.team_id, distinct_id, missing, plan.person.properties or {}, event_source="person_divergence_reset"
    )


def send_set_once(
    team_id: int,
    distinct_id: str,
    missing: dict[str, Any],
    existing: dict[str, Any],
    *,
    event_source: str,
    event_name: str = "$set",
    extra_properties: dict[str, Any] | None = None,
) -> datatypes.RepairOutcome | None:
    """Send `missing` to ingestion as $set_once on the person that owns `distinct_id`, or return why it was not
    sent. `existing` is that person's Postgres properties, which bound the size of the merged result."""
    # Every member can read the $set event, and event reads apply event property restrictions only, so a team with
    # any property rule could expose a person property that some member is denied.
    if team_has_property_access_rules(team_id=team_id):
        return "skipped_stale_merge_restricted"
    if len(json.dumps({**missing, **existing})) > _STALE_MERGE_MAX_BYTES:
        return "skipped_stale_merge_too_large"
    try:
        token = Team.objects.only("api_token").get(id=team_id).api_token
        capture_internal(
            token=token,
            event_name=event_name,
            event_source=event_source,
            distinct_id=distinct_id,
            timestamp=datetime.now(UTC),
            properties={**(extra_properties or {}), "$set_once": missing},
            process_person_profile=True,
        ).raise_for_status()
    except Exception:
        return "skipped_stale_merge_failed"
    return None
