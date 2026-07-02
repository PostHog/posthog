from .. import format_access_control_warnings, format_warehouse_sync_warnings

_AC = {"type": "access_control", "resource": "dashboard", "message": "2 dashboards"}
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
    assert "partial result set" in block
    assert "- 2 dashboards" in block


def test_warning_blocks_split_the_shared_field_by_shape():
    # Both kinds share the `warnings` list; each formatter must pick out only its own.
    response = {"warnings": [_SYNC, _AC]}
    assert "sync failed" in format_warehouse_sync_warnings(response)
    assert "2 dashboards" not in format_warehouse_sync_warnings(response)
    assert "2 dashboards" in format_access_control_warnings(response)
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
