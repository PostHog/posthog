import json
import asyncio
import datetime as dt
import operator

import aiokafka

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils.records import get_record_batch_from_queue


async def assert_clickhouse_records_in_kafka(
    clickhouse_client: ClickHouseClient,
    team_id: int,
    topic: str,
    hosts: list[str],
    security_protocol: str,
    sort_key: str,
    batch_export_model: BatchExportModel | BatchExportSchema | None,
    date_ranges: list[tuple[dt.datetime, dt.datetime]],
    backfill_details: BackfillDetails | None = None,
    expected_fields: list[str] | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    is_backfill: bool = False,
):
    json_columns = {"properties", "set", "set_once", "person_properties"}

    consumer = aiokafka.AIOKafkaConsumer(
        topic,
        group_id="test_batch_exports",
        bootstrap_servers=hosts,
        security_protocol=security_protocol,
        auto_offset_reset="earliest",
    )
    produced_records = []

    async with consumer:
        while True:
            try:
                async with asyncio.timeout(5):
                    msg = await consumer.getone()
            except TimeoutError:
                break

            record = json.loads(msg.value)

            if (
                is_backfill
                and (is_last := record.get("isLastBackfillingMessage", None)) is not None
                and is_last is True
            ):
                break

            for timestamp_column in ("timestamp", "created_at"):
                if (timestamp_str := record.get(timestamp_column)) is not None and isinstance(timestamp_str, str):
                    record[timestamp_column] = dt.datetime.fromisoformat(timestamp_str)

            produced_records.append(record)

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
                expected_record = {}

                for k, v in record.items():
                    if k in json_columns and v is not None:
                        expected_record[k] = json.loads(v)
                    elif isinstance(v, dt.datetime):
                        expected_record[k] = v.replace(tzinfo=dt.UTC)
                    else:
                        expected_record[k] = v

                expected_records.append(expected_record)

    produced_column_names = list(produced_records[0].keys())
    expected_column_names = [key for key in expected_records[0].keys() if key != "_inserted_at"]
    produced_column_names.sort()
    expected_column_names.sort()

    expected_records.sort(key=operator.itemgetter(sort_key))
    for record in expected_records:
        record.pop("_inserted_at")

    assert (
        produced_column_names == expected_column_names
    ), f"Expected column names to be '{expected_column_names}', got '{produced_column_names}'"
    assert produced_records[0] == expected_records[0]
    assert produced_records == expected_records
    assert len(produced_records) == len(expected_records)
