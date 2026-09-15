from typing import Any

import pytest

from posthog.query_scan.findings import ASSISTANT_GOAL, ASSISTANT_RULES

from .. import format_access_control_warnings, format_query_scan_warnings, format_warehouse_sync_warnings

_AC = {
    "type": "access_control",
    "resources": ["dashboard"],
    "message": "Results may exclude dashboards you don't have access to",
}
_SCAN_FINDING = {
    "type": "query_scan",
    "kind": "no_event_filter",
    "reason": "in_or",
    "message": (
        "This query has an event filter, but it is inside an OR with another condition, so ClickHouse "
        "could not use it. Put the event filter outside the OR: `WHERE event IN ('…') AND (… OR …)`."
    ),
    "fix": "Move the event filter out of the OR so it stands on its own. Change nothing else.",
}
_SCAN_SHOWN: dict[str, Any] = {"mode": "show", "rows_read": 4_200_000_000, "duration_ms": 12_300, "status": "done"}


def _scan(**overrides: Any) -> dict[str, Any]:
    return {**_SCAN_SHOWN, **overrides}


_SYNC = {
    "type": "warehouse_sync",
    "table_name": "stripe_charges",
    "schema_name": "charges",
    "source_type": "Stripe",
    "status": "Failed",
    "message": "sync failed",
}


def test_access_control_warning_block_surfaces_message_from_shared_field():
    block = format_access_control_warnings({"warnings": [_AC]})
    assert block.startswith("[Access control]")
    assert "- Results may exclude dashboards you don't have access to" in block


def test_warning_blocks_split_the_shared_field_by_shape():
    # Both kinds share the `warnings` list; each formatter must pick out only its own.
    response = {"warnings": [_SYNC, _AC]}
    assert "sync failed" in format_warehouse_sync_warnings(response)
    assert "may exclude" not in format_warehouse_sync_warnings(response)
    assert "may exclude dashboards" in format_access_control_warnings(response)
    assert "sync failed" not in format_access_control_warnings(response)
    # Concatenated blocks must not run together: each ends with a blank line, so the next
    # header doesn't read as a bullet of the previous block in LLM-facing plain text.
    combined = format_warehouse_sync_warnings(response) + format_access_control_warnings(response)
    assert "\n\n[Access control" in combined


def test_no_access_control_warning_block_when_nothing_filtered():
    assert format_access_control_warnings({"results": [], "warnings": None}) == ""
    assert format_access_control_warnings({"results": [], "warnings": [_SYNC]}) == ""


def test_response_warnings_union_round_trips_both_kinds():
    # The shared `warnings` field is a union; serializing must keep each member's own shape,
    # not coerce an access control warning into the warehouse-sync schema.
    from posthog.schema import AccessControlFilterWarning, DataWarehouseSyncWarning, HogQLQueryResponse

    response = HogQLQueryResponse(
        results=[],
        warnings=[
            DataWarehouseSyncWarning(**_SYNC),
            AccessControlFilterWarning(**_AC),
        ],
    )
    dumped = response.model_dump(mode="json")["warnings"]
    assert dumped[0]["table_name"] == "stripe_charges"
    assert dumped[1] == _AC


@pytest.mark.parametrize(
    "scan,expected_lead",
    [
        pytest.param(
            _SCAN_SHOWN,
            "This query read 4.2 billion rows in 12.3 s.",
            id="finished",
        ),
        pytest.param(
            _scan(killed=True),
            "ClickHouse stopped this query after 12.3 s, having read 4.2 billion rows.",
            id="killed",
        ),
    ],
)
def test_query_scan_block_leads_with_the_run_and_ends_with_the_standing_instruction(scan, expected_lead):
    block = format_query_scan_warnings({"query_scan": scan, "warnings": [_SCAN_FINDING]})

    lines = block.splitlines()
    assert lines[0] == "<query_scan_warning>"
    assert lines[1] == ASSISTANT_GOAL
    assert lines[3] == expected_lead
    closing = lines.index("</query_scan_warning>")
    assert lines[closing - 1] == ASSISTANT_RULES
    finding_lines = [line for line in lines[4 : closing - 1] if line.startswith("- ")]
    assert len(finding_lines) == 1
    assert finding_lines[0].startswith(f"- {_SCAN_FINDING['kind']}")
    assert str(_SCAN_FINDING["fix"]).split(".")[0] in finding_lines[0]


def test_compact_query_scan_block_carries_two_findings():
    findings = [{**_SCAN_FINDING, "fix": f"finding {index}"} for index in range(3)]

    block = format_query_scan_warnings({"query_scan": _scan(killed=True), "warnings": findings}, compact=True)

    assert "finding 0" in block
    assert "finding 1" in block
    assert "finding 2" not in block


@pytest.mark.parametrize(
    "response,expected",
    [
        pytest.param({"query_scan": _SCAN_SHOWN, "warnings": []}, "", id="analyzed_with_no_findings"),
        pytest.param(
            {"query_scan": _scan(mode="log_only"), "warnings": [_SCAN_FINDING]},
            "",
            id="log_only_shows_nothing",
        ),
        pytest.param({"warnings": [_SCAN_FINDING]}, "", id="unflagged_team_has_no_scan"),
        pytest.param(
            {"query_scan": _scan(status="pending", duration_ms=900), "warnings": []},
            "",
            id="pending_below_the_floor",
        ),
        pytest.param(
            {"query_scan": _scan(status="pending"), "warnings": []},
            "<query_scan_warning>This query read 4.2 billion rows in 12.3 s. This is likely far more "
            "than needed; check the event filter and the start date before running it again."
            "</query_scan_warning>\n\n",
            id="pending_over_the_floor_gets_the_short_form",
        ),
    ],
)
def test_query_scan_block_gating(response, expected):
    assert format_query_scan_warnings(response) == expected
