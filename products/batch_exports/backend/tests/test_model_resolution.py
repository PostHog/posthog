import pytest

from products.batch_exports.backend.service import BatchExportModel, migrate_batch_export_model
from products.batch_exports.backend.temporal.record_batch_model import (
    HogQLQueryRecordBatchModel,
    SessionsRecordBatchModel,
    resolve_batch_exports_model,
)


@pytest.mark.parametrize(
    "legacy",
    [
        None,
        BatchExportModel(name="events", schema=None),
        BatchExportModel(name="events", schema=None, filters=[{"key": "event", "value": "example"}]),
        BatchExportModel(
            name="events",
            schema={"fields": [{"expression": "event", "alias": "name"}], "values": {"value": 1.5}},
            filters=[{"key": "event", "value": "example"}],
        ),
        BatchExportModel(name="persons", schema=None),
        BatchExportModel(name="sessions", schema=None),
        BatchExportModel(
            name="hogql",
            schema=None,
            hogql_query="SELECT event FROM events WHERE timestamp < {data_interval_end}",
            user_id=42,
            hogql_modifiers={"convertToProjectTimezone": False},
        ),
    ],
)
def test_migrated_model_preserves_query_inputs(legacy: BatchExportModel | None) -> None:
    _, old_record_model, old_name, old_fields, old_filters, old_values = resolve_batch_exports_model(
        team_id=1, batch_export_model=legacy, batch_export_id="export", is_backfill=True
    )
    _, record_model, name, fields, filters, values = resolve_batch_exports_model(
        team_id=1,
        batch_export_model=migrate_batch_export_model(legacy),
        batch_export_id="export",
        is_backfill=True,
    )

    assert (name, fields, filters or [], values) == (old_name, old_fields, old_filters or [], old_values)
    assert type(record_model) is type(old_record_model)
    if isinstance(record_model, SessionsRecordBatchModel):
        assert record_model.is_backfill is True
        assert record_model.team_id == 1
        assert record_model.batch_export_id == "export"
    elif isinstance(record_model, HogQLQueryRecordBatchModel):
        assert isinstance(old_record_model, HogQLQueryRecordBatchModel)
        assert record_model.hogql_query == old_record_model.hogql_query
        assert record_model.hogql_modifiers == old_record_model.hogql_modifiers
        assert record_model.user_id == 42
        assert record_model.wait_for_data_interval_end is True
