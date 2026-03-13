import json
import typing
import datetime as dt
import operator

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.destinations.workflows_batch_export import workflows_default_fields
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import get_record_batch_from_queue

TeamId = str
HogFunctionId = str
Body = bytes


class RequestData(typing.NamedTuple):
    team_id: TeamId
    hog_function_id: HogFunctionId
    body: Body


async def assert_clickhouse_records_were_handled(
    clickhouse_client: ClickHouseClient,
    handler,
    hog_function_id,
    team_id: int,
    sort_key: str,
    batch_export_model: BatchExportModel | BatchExportSchema | None,
    batch_export_id: str,
    date_ranges: list[tuple[dt.datetime, dt.datetime]],
    backfill_details: BackfillDetails | None = None,
    expected_fields: list[str] | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    is_backfill: bool = False,
):
    json_columns = {"properties", "set", "set_once", "person_properties"}

    handled_records = [json.loads(request.body)["clickhouse_event"] for request in handler.data]
    hog_function_ids = {request.hog_function_id for request in handler.data}

    assert hog_function_id in hog_function_ids and len(hog_function_ids) == 1, (
        f"Expected only '{hog_function_id}' but got '{hog_function_ids}'"
    )

    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            model_name = batch_export_model.name
            fields = batch_export_model.schema["fields"] if batch_export_model.schema is not None else None
            filters = batch_export_model.filters
            extra_query_parameters = (
                batch_export_model.schema["values"] if batch_export_model.schema is not None else None
            )
        else:
            model_name = "custom"
            fields = batch_export_model["fields"]
            filters = None
            extra_query_parameters = batch_export_model["values"]
    else:
        model_name = "events"
        extra_query_parameters = None
        fields = None
        filters = None

    expected_records = []
    queue = RecordBatchQueue()
    if model_name == "sessions":
        producer = Producer(model=SessionsRecordBatchModel(team_id))
    else:
        producer = Producer()

    for data_interval_start, data_interval_end in date_ranges:
        producer_task = await producer.start(
            queue=queue,
            model_name=model_name,
            team_id=team_id,
            full_range=(data_interval_start, data_interval_end),
            done_ranges=[],
            fields=fields,
            filters=filters,
            exclude_events=exclude_events,
            include_events=include_events,
            is_workflows=True,
            destination_default_fields=workflows_default_fields(batch_export_id),
            is_backfill=backfill_details is not None,
            backfill_details=backfill_details,
            extra_query_parameters=extra_query_parameters,
        )
        while True:
            record_batch = await get_record_batch_from_queue(queue, producer_task)

            if record_batch is None:
                break

            select = record_batch.column_names
            if expected_fields:
                select = expected_fields

            for record in record_batch.select(select).to_pylist():
                expected_record: dict[str, typing.Any] = {}

                for k, v in record.items():
                    if k == "_inserted_at":
                        continue
                    elif k in json_columns and v is not None:
                        if v == "":
                            expected_record[k] = None
                        else:
                            expected_record[k] = json.loads(v)
                    elif isinstance(v, dt.datetime):
                        expected_record[k] = v.replace(tzinfo=dt.UTC).isoformat()
                    else:
                        expected_record[k] = v

                expected_records.append(expected_record)

    produced_column_names = list(handled_records[0].keys())
    expected_column_names = [key for key in expected_records[0].keys() if key != "_inserted_at"]
    produced_column_names.sort()
    expected_column_names.sort()

    expected_records.sort(key=operator.itemgetter(sort_key))
    handled_records.sort(key=operator.itemgetter(sort_key))

    assert produced_column_names == expected_column_names, (
        f"Expected column names to be '{expected_column_names}', got '{produced_column_names}'"
    )
    assert handled_records[0] == expected_records[0]
    assert handled_records == expected_records
    assert len(handled_records) == len(expected_records)
