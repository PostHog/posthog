import pytest

import orjson

from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from posthog.temporal.data_imports.sources.stripe.stripe import _webhook_table_transformer


def _make_event(event_id: str, obj_id: str, event_created: int, obj_fields: dict | None = None) -> dict:
    """Build a Stripe event dict matching the schema produced by _transform_webhook_table.

    The data column is a JSON string, matching what production produces after
    _transform_webhook_table parses payload_json via orjson.loads and then
    table_from_py_list serializes nested dicts to JSON strings.
    """
    obj = {"id": obj_id, "object": "customer", "balance": 0, **(obj_fields or {})}
    return {
        "id": event_id,
        "object": "event",
        "created": event_created,
        "data": orjson.dumps({"object": obj}).decode(),
    }


def _build_table(events: list[dict]):
    return table_from_py_list(events)


class TestWebhookTableTransformer:
    def test_single_event(self):
        table = _build_table([_make_event("evt_1", "cus_1", 1000, {"name": "Alice"})])
        result = _webhook_table_transformer(table)

        assert result.num_rows == 1
        assert result.column("id").to_pylist() == ["cus_1"]
        assert result.column("name").to_pylist() == ["Alice"]

    def test_deduplicates_same_object_keeps_latest(self):
        events = [
            _make_event("evt_1", "cus_1", 1000, {"name": "Alice"}),
            _make_event("evt_2", "cus_1", 2000, {"name": "Alice Updated"}),
        ]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == 1
        assert result.column("id").to_pylist() == ["cus_1"]
        assert result.column("name").to_pylist() == ["Alice Updated"]

    def test_deduplicates_same_object_keeps_latest_regardless_of_order(self):
        events = [
            _make_event("evt_2", "cus_1", 2000, {"name": "Latest"}),
            _make_event("evt_1", "cus_1", 1000, {"name": "Older"}),
        ]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == 1
        assert result.column("name").to_pylist() == ["Latest"]

    def test_different_objects_preserved(self):
        events = [
            _make_event("evt_1", "cus_1", 1000, {"name": "Alice"}),
            _make_event("evt_2", "cus_2", 1000, {"name": "Bob"}),
        ]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == 2
        ids = sorted([id for id in result.column("id").to_pylist() if id is not None])
        assert ids == ["cus_1", "cus_2"]

    def test_many_duplicates_of_same_object(self):
        events = [_make_event(f"evt_{i}", "cus_1", 1000 + i, {"name": f"v{i}"}) for i in range(6)]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == 1
        assert result.column("name").to_pylist() == ["v5"]

    def test_mixed_duplicates_and_unique(self):
        events = [
            _make_event("evt_1", "cus_1", 1000, {"name": "A old"}),
            _make_event("evt_2", "cus_2", 1500, {"name": "B"}),
            _make_event("evt_3", "cus_1", 2000, {"name": "A new"}),
            _make_event("evt_4", "cus_3", 1200, {"name": "C"}),
            _make_event("evt_5", "cus_2", 1600, {"name": "B updated"}),
        ]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == 3
        rows = {row["id"]: row["name"] for row in result.to_pylist()}
        assert rows == {"cus_1": "A new", "cus_2": "B updated", "cus_3": "C"}

    def test_same_created_timestamp_keeps_last_seen(self):
        events = [
            _make_event("evt_1", "cus_1", 1000, {"name": "First"}),
            _make_event("evt_2", "cus_1", 1000, {"name": "Second"}),
        ]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == 1

    @pytest.mark.parametrize("count", [1, 10, 100])
    def test_handles_various_sizes(self, count):
        events = [_make_event(f"evt_{i}", f"cus_{i}", 1000 + i) for i in range(count)]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == count

    def test_null_data_rows_skipped(self):
        events = [
            {"id": "evt_1", "object": "event", "created": 1000, "data": None},
            _make_event("evt_2", "cus_1", 2000, {"name": "Valid"}),
        ]
        result = _webhook_table_transformer(_build_table(events))

        assert result.num_rows == 1
        assert result.column("id").to_pylist() == ["cus_1"]
