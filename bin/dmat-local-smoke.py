#!/usr/bin/env python
"""Local smoke-test driver for the dynamic property materialization (dmat) system.

See docs/internal/dmat-local-testing.md for the full test plan. This script automates the
slow end-to-end stages (workflow trigger, fill the column pool, send events through the
HTTP capture endpoint) so an operator can pick up where the parity tests leave off and
validate the full read/write loop on a local PostHog dev environment.

Phases (run with --phase=<name>):

    full              Default. PENDING → BACKFILL → READY plus before-vs-after row-count check.
    bootstrap         Just create one PENDING slot for the named property.
    send-events       Send one or more capture events for the named property.
    trigger-workflow  Kick BackfillMaterializedPropertiesBatchWorkflow once. Idempotent.
    fill-pool         Pre-fill the dmat pool with stub READY slots to force compaction
                      on the next workflow run. Use with --slot-count.
    cleanup           Delete every MaterializedColumnSlot. Does NOT clear column data.

Run once at the start of your testing session to make sure everything is wired:

    python bin/dmat-local-smoke.py --team-id 1 --property dmat_test_prop

This script is intentionally chatty — its job is to make every transition observable so
you can correlate Django state, plugin-server logs, ClickHouse rows, and HogQL output.
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
import asyncio
import argparse
from typing import Any
from urllib import request as urllib_request

# -- Django bootstrap (same dance as bin/manage.py) -----------------------------------------
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

# -- Django imports must come AFTER django.setup() ------------------------------------------

from django.conf import settings  # noqa: E402

from posthog.clickhouse.client import sync_execute  # noqa: E402
from posthog.models import MaterializedColumnSlot, MaterializedColumnSlotState, PropertyDefinition, Team  # noqa: E402
from posthog.models.event.sql import DMAT_STRING_COLUMN_COUNT  # noqa: E402
from posthog.temporal.backfill_materialized_property.workflows import (  # noqa: E402
    BackfillMaterializedPropertiesBatchInputs,
    BackfillMaterializedPropertiesBatchWorkflow,
)
from posthog.temporal.common.client import async_connect  # noqa: E402

from products.event_definitions.backend.models.property_definition import PropertyType  # noqa: E402

# -- helpers --------------------------------------------------------------------------------


def _say(msg: str) -> None:
    """Single-line status output — not log-level, just a visible breadcrumb."""
    print(f"[dmat-smoke] {msg}", flush=True)  # noqa: T201 — interactive smoke script, print is the UX


def _team_or_die(team_id: int) -> Team:
    try:
        return Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        sys.exit(f"team_id={team_id} does not exist — run `./bin/start` and seed a team first")


def _ensure_property_def(team: Team, name: str) -> PropertyDefinition:
    """Get-or-create the property definition we'll attach the slot to.

    The dmat API's `assign_slot` requires the property to be String-typed and not a
    PostHog system property, so we set those here. The TS-side coercion test fixture
    covers a richer set of types — local smoke is just the happy String path.
    """
    prop, created = PropertyDefinition.objects.get_or_create(
        team=team,
        name=name,
        type=PropertyDefinition.Type.EVENT,
        defaults={"property_type": PropertyType.String},
    )
    if not prop.property_type:
        prop.property_type = PropertyType.String
        prop.save(update_fields=["property_type"])
    if created:
        _say(f"created PropertyDefinition id={prop.id} name={name} type=String")
    return prop


def _post_capture(team: Team, prop_name: str, count: int, base_url: str) -> int:
    """Send N events to the local capture endpoint with the named property set.

    The capture endpoint runs the real plugin-server pipeline locally (when bin/start
    is up), so this exercises the slot manager + extractDynamicMaterializedColumns
    path. Returns the count of events accepted.
    """
    accepted = 0
    for i in range(count):
        payload = {
            "api_key": team.api_token,
            "event": "$pageview",
            "distinct_id": f"dmat-smoke-user-{i}",
            "properties": {
                prop_name: f"value_{i}_{int(time.time() * 1000)}",
                "$current_url": "https://dmat-smoke-test/",
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            f"{base_url}/i/v0/e/",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=5) as resp:
                if resp.status in (200, 201, 202):
                    accepted += 1
        except Exception as e:
            _say(f"warn: capture request failed: {e!r}")
    return accepted


def _create_pending_slot(team: Team, prop_def: PropertyDefinition) -> MaterializedColumnSlot:
    """Create a PENDING slot directly. Mirrors the API's `assign_slot` action without
    needing a logged-in staff user — this script runs in a Django shell, not an HTTP client.
    """
    existing = MaterializedColumnSlot.objects.filter(team=team, property_definition=prop_def).first()
    if existing:
        _say(f"slot already exists id={existing.id} state={existing.state} slot_index={existing.slot_index}")
        return existing
    slot = MaterializedColumnSlot.objects.create(
        team=team,
        property_definition=prop_def,
        slot_index=None,
        state=MaterializedColumnSlotState.PENDING,
    )
    _say(f"created PENDING slot id={slot.id}")
    return slot


def _dmat_slot_assignments_state(team_id: int) -> list[tuple[int, int, str]]:
    """Read the rows the populate activity wrote into the CH dict-source table for this team.

    The dict-backed mutation reads `dmat_slot_assignments_dict` at runtime; that dict is
    sourced from the `dmat_slot_assignments` ClickHouse table, populated by the
    `populate_slot_assignments` activity each cycle. This helper lets the smoke run print
    the table state before/after the mutation so an operator can correlate workflow
    execution with what the mutation actually saw.
    """
    rows = sync_execute(
        "SELECT team_id, column_index, property_name FROM dmat_slot_assignments FINAL "
        "WHERE team_id = %(team_id)s ORDER BY column_index",
        {"team_id": team_id},
    )
    return [(int(r[0]), int(r[1]), r[2]) for r in rows]


def _clickhouse_distribution_for_slot(team_id: int, slot_index: int, prop_name: str) -> dict[str, int]:
    """Count events with the property set, split by whether the dmat column is populated.

    Used to verify the historical backfill ran: BEFORE the workflow, every event has
    `dmat_string_<idx> IS NULL`. AFTER the workflow's mutation completes, every event
    that has the property in JSON should also have a non-null dmat column.
    """
    rows = sync_execute(
        f"""
        SELECT
            countIf(JSONHas(properties, %(prop)s)) AS json_has,
            countIf(dmat_string_{int(slot_index)} IS NOT NULL) AS dmat_populated,
            countIf(JSONHas(properties, %(prop)s) AND dmat_string_{int(slot_index)} IS NULL) AS json_only
        FROM events
        WHERE team_id = %(team_id)s
        """,
        {"team_id": team_id, "prop": prop_name},
    )
    json_has, dmat_populated, json_only = rows[0]
    return {"json_has": json_has, "dmat_populated": dmat_populated, "json_only": json_only}


async def _trigger_workflow(cache_refresh_wait_seconds: int = 10) -> str:
    """Run the batched workflow once, blocking until completion. Returns the workflow id."""
    client = await async_connect()
    workflow_id = f"dmat-smoke-{uuid.uuid4()}"
    _say(f"executing BackfillMaterializedPropertiesBatchWorkflow id={workflow_id}")
    await client.execute_workflow(
        BackfillMaterializedPropertiesBatchWorkflow.run,
        BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=cache_refresh_wait_seconds),
        id=workflow_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
    )
    _say("workflow completed")
    return workflow_id


# -- phases ---------------------------------------------------------------------------------


def phase_bootstrap(team: Team, prop_name: str) -> MaterializedColumnSlot:
    prop_def = _ensure_property_def(team, prop_name)
    return _create_pending_slot(team, prop_def)


def phase_send_events(team: Team, prop_name: str, count: int, base_url: str) -> None:
    accepted = _post_capture(team, prop_name, count, base_url)
    _say(f"sent {count} events, {accepted} accepted by capture")


def phase_trigger_workflow(cache_refresh_wait_seconds: int = 10) -> None:
    asyncio.run(_trigger_workflow(cache_refresh_wait_seconds=cache_refresh_wait_seconds))


def phase_fill_pool(slot_count: int) -> None:
    """Create `slot_count` stub READY slots across `slot_count` distinct teams.

    Why one team per slot: the per-team uniqueness invariant on `(team, slot_index)` would
    cap a single team at MAX_SLOTS_PER_TEAM=5, so a single team can't fill 96 columns.
    Spreading across teams (even synthetic ones) is how the global pool gets exhausted.
    """
    if slot_count >= DMAT_STRING_COLUMN_COUNT:
        sys.exit(
            f"--slot-count={slot_count} would consume the entire dmat pool "
            f"(only {DMAT_STRING_COLUMN_COUNT} columns exist), pick something < {DMAT_STRING_COLUMN_COUNT}"
        )
    org = Team.objects.first().organization  # type: ignore[union-attr]
    if org is None:
        sys.exit("no organization found — bootstrap your local PostHog before running this")
    created = 0
    for i in range(slot_count):
        team_name = f"dmat-fill-team-{i}"
        team, _ = Team.objects.get_or_create(organization=org, name=team_name)
        prop_name = f"dmat_fill_prop_{i}"
        prop_def, _ = PropertyDefinition.objects.get_or_create(
            team=team,
            name=prop_name,
            type=PropertyDefinition.Type.EVENT,
            defaults={"property_type": PropertyType.String},
        )
        if MaterializedColumnSlot.objects.filter(team=team, property_definition=prop_def).exists():
            continue
        MaterializedColumnSlot.objects.create(
            team=team,
            property_definition=prop_def,
            slot_index=i,
            state=MaterializedColumnSlotState.READY,
        )
        created += 1
    _say(f"created {created} stub READY slots (filling slot_index 0..{slot_count - 1})")


def phase_cleanup() -> None:
    n = MaterializedColumnSlot.objects.count()
    MaterializedColumnSlot.objects.all().delete()
    _say(f"deleted {n} MaterializedColumnSlot rows (column data left intact)")


def phase_full(team: Team, prop_name: str, base_url: str) -> None:
    """End-to-end: send pre-slot events → create slot → run workflow → send post-slot events
    → assert backfill populated historical rows AND new rows route through dmat."""
    prop_def = _ensure_property_def(team, prop_name)

    _say("=== phase 1: pre-slot events (JSON-only path) ===")
    _post_capture(team, prop_name, 5, base_url)

    _say("=== phase 2: create PENDING slot ===")
    slot = _create_pending_slot(team, prop_def)

    _say("=== phase 3: events while slot is PENDING (still JSON-only) ===")
    _post_capture(team, prop_name, 5, base_url)

    _say("=== phase 4: trigger backfill workflow ===")
    asyncio.run(_trigger_workflow(cache_refresh_wait_seconds=10))

    slot.refresh_from_db()
    if slot.state != MaterializedColumnSlotState.READY:
        sys.exit(f"slot did not transition to READY (got {slot.state}). Check temporal worker logs.")
    if slot.slot_index is None:
        sys.exit("slot transitioned to READY but slot_index is NULL — this should not happen")
    _say(f"slot state={slot.state} slot_index={slot.slot_index}")

    # The workflow's populate_slot_assignments activity should have written this team's
    # (slot_index, property_name) to dmat_slot_assignments and reloaded the dict before
    # the mutation ran. Surface the table state so an operator can confirm the dict-backed
    # path was actually exercised.
    dict_rows = _dmat_slot_assignments_state(team.id)
    _say(f"dmat_slot_assignments rows for team={team.id}: {dict_rows}")
    if not any(r[1] == slot.slot_index and r[2] == prop_name for r in dict_rows):
        sys.exit(
            "FAIL: populate_slot_assignments did not write this team's slot to the dict-source "
            "table. The dict-backed mutation would silently no-op against this slot."
        )

    # Allow a moment for the events MV to flush the latest batch.
    time.sleep(2)

    _say("=== phase 5: events after READY (plugin-server should be writing dmat columns) ===")
    _post_capture(team, prop_name, 5, base_url)
    time.sleep(3)  # let MV catch up

    _say("=== phase 6: ClickHouse distribution check ===")
    dist = _clickhouse_distribution_for_slot(team.id, slot.slot_index, prop_name)
    _say(f"distribution: {dist}")
    if dist["json_only"] != 0:
        sys.exit(
            f"FAIL: {dist['json_only']} events have the property in JSON but no dmat column. "
            "Either the historical backfill mutation didn't run or plugin-server isn't dual-writing."
        )
    _say(f"OK: all {dist['json_has']} matching rows have dmat_string_{slot.slot_index} populated")

    _say("=== phase 7: HogQL renders the dmat column, not JSONExtractRaw ===")
    from posthog.hogql.context import HogQLContext
    from posthog.hogql.parser import parse_select
    from posthog.hogql.printer import prepare_and_print_ast

    expr = parse_select(f"SELECT properties.{prop_name} FROM events")
    sql, _ctx = prepare_and_print_ast(
        expr,
        HogQLContext(team_id=team.id, team=team, enable_select_queries=True),
        "clickhouse",
    )
    if f"dmat_string_{slot.slot_index}" not in sql:
        sys.exit(f"FAIL: HogQL did not rewrite to dmat column. SQL was:\n{sql}")
    if "JSONExtractRaw" in sql:
        sys.exit(f"FAIL: HogQL emitted JSONExtractRaw despite a READY slot. SQL was:\n{sql}")
    _say("OK: HogQL routes through dmat_string_<idx>")

    _say("=== ALL CHECKS PASSED ===")


# -- argv -----------------------------------------------------------------------------------


def _parse_args() -> Any:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--phase",
        choices=["full", "bootstrap", "send-events", "trigger-workflow", "fill-pool", "cleanup"],
        default="full",
    )
    p.add_argument("--team-id", type=int, default=1)
    p.add_argument("--property", default="dmat_test_prop", help="property name to materialize")
    p.add_argument("--count", type=int, default=5, help="event count for send-events phase")
    p.add_argument("--slot-count", type=int, default=96, help="stub slots to create in fill-pool phase")
    p.add_argument("--cache-refresh-wait-seconds", type=int, default=10)
    p.add_argument("--base-url", default="http://localhost:8000", help="capture endpoint base URL")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.phase == "full":
        team = _team_or_die(args.team_id)
        phase_full(team, args.property, args.base_url)
    elif args.phase == "bootstrap":
        team = _team_or_die(args.team_id)
        phase_bootstrap(team, args.property)
    elif args.phase == "send-events":
        team = _team_or_die(args.team_id)
        phase_send_events(team, args.property, args.count, args.base_url)
    elif args.phase == "trigger-workflow":
        phase_trigger_workflow(args.cache_refresh_wait_seconds)
    elif args.phase == "fill-pool":
        phase_fill_pool(args.slot_count)
    elif args.phase == "cleanup":
        phase_cleanup()
    else:
        sys.exit(f"unknown phase {args.phase!r}")


if __name__ == "__main__":
    main()
