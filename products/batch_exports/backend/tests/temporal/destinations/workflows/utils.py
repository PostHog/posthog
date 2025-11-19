import json
import datetime as dt
import operator

import aiokafka

from posthog.batch_exports.service import BackfillDetails, BatchExportModel, BatchExportSchema
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import redshift_default_fields
from products.batch_exports.backend.temporal.record_batch_model import SessionsRecordBatchModel
from products.batch_exports.backend.temporal.spmc import Producer, RecordBatchQueue
from products.batch_exports.backend.tests.temporal.utils import get_record_batch_from_queue


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
):
    json_columns = {"properties", "set", "set_once", "person_properties"}

    consumer = aiokafka.AIOKafkaConsumer(
        topic, group_id="test-batch-exports", bootstrap_servers=hosts, security_protocol=security_protocol
    )
    produced_records = []
    await consumer.start()
    async for msg in consumer:
        record = json.loads(msg.value)

        if (event := record.get("event", None)) is not None and event == "$backfill_complete":
            break

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
            destination_default_fields=redshift_default_fields(),
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
                    if k == "_inserted_at":
                        # _inserted_at is not exported, only used for tracking progress.
                        continue

                    elif k in json_columns and v is not None:
                        expected_record[k] = json.loads(v)
                    elif isinstance(v, dt.datetime):
                        expected_record[k] = v.replace(tzinfo=dt.UTC)
                    else:
                        expected_record[k] = v

                expected_records.append(expected_record)

    produced_column_names = list(produced_records[0].keys())
    expected_column_names = list(expected_records[0].keys())
    produced_column_names.sort()
    expected_column_names.sort()

    expected_records.sort(key=operator.itemgetter(sort_key))

    assert (
        produced_column_names == expected_column_names
    ), f"Expected column names to be '{expected_column_names}', got '{produced_column_names}'"
    assert produced_records[0] == expected_records[0]
    assert produced_records == expected_records
    assert len(produced_records) == len(expected_records)
