# Data Stack - Import Pipeline

## How to detect a OOM:

In the logs, you'll often see the last operation of the job being a delta merge - such as `Merging partition=...`. Followed by heartbeat logs. There will then be a 2-min gap between the last heartbeat and the start of the next retry, or if its the last attempt, then you'll see a 2-min gap before a `activity Heartbeat timeout` error log. The 2-mins (as of Oct 2025) comes from the current `heartbeat_timeout` set on the `import_data_activity` in the workflow.

Typically only incremental syncs can cause an OOM on a pod, this affects all jobs running on the pod at the time, causing them all to retry if they have retry attempts available.

Some jobs may look like they cause OOMs due to how they're always running when an OOM occurs. This is usually the case for long-running jobs, such as big Stripe tables or any other full-refresh/append-only jobs. These jobs are almost always not the cause, and so it's best to just focus on the incremental jobs when this happens.

## Why does this happen?

This happens during a deltalake merge because we have to read the whole partition from S3 (or the whole table if partitioning isn't enabled for the table) to merge data into it. If the partition has great ordering, then a lot of data can be skipped via parquet row group min/max's, but this often isn't the case, and so we often have to load the whole partition into memory. The library we use for this attempts to be clever with how it reads the data in, but it doesn't always work out in our favour.

I've found that at worst case, we require roughly 20x the memory of what the compressed partition size is at rest on S3. So, if the partition is 5 GB in S3, then I'd expect to need (at worst case) roughly 100 GB memory on the pod to merge the data without fail. Our pods currently run with memory limits of 29 GB - so any partition over 1.5 GB will likely result in a OOM at some point.

Some tables may not be partitioned. This usually comes down to one of two reasons. (1) the table existed pre-partitioning logic, or (2) the table can't be partitioned due to a lack of stable `datetime`, a numerical `id`, or a stable primary key. If the reason is (1), then resyncing the table from scratch usually solves the issue. If the reason is (2), then we usually need to dive into the table data and figure out if there is a new method we can add to partition the table.

In other cases, the table is already partitioned, but the partitions have gotten too big - usually because the table has outgrown the original partitioning method. When this happens, we need to resync the table and allow the system to implement a new partitioning method.

On rare occasions, OOMs can be caused by tables that have too wide data - that is, a column (or columns) with a lot of data. Such as LLM traces, or full email bodies. This causes us to load too much data on the pod before we get to merging - we have practices in place to handle this, but it's not 100% effective. Majority of the time we have dynamic chunking that will only ingest data up to 150 MB in CPython/Arrow before flushing it out to S3. We don't have a guideline for how to deal with these syncs, they're very rare and we handle them on a case-by-case basis.

## Repartitioning

The `ExternalDataSchema` model stores partitioning settings in the `sync_type_config` json column. We have all the possible settings listed at `posthog/warehouse/models/external_data_schema.py#L57`.

More info on what partitioning options and the different modes can be found here: [https://github.com/PostHog/posthog/blob/master/posthog/temporal/data_imports/sources/README.md#partitioning](https://github.com/PostHog/posthog/blob/master/posthog/temporal/data_imports/sources/README.md#partitioning)

If a table has the `partition_mode` set to `datetime`, then you'll likely see that `partition_format` is set to either `month` or `None` (which means `month`). To repartition by `day`, you'll want to update this value to `day` and then perform a resync below.

If the `partition_mode` is either `md5` or `numerical`, then you'll want to do a standard resync by following the below instructions.

If the table has no partitions, but it could be partitioned, then again just resync the table following below.

## How to resync

When we resync a table, we do so from a k8s pod. We have the ability to disable billing for a sync via this method meaning that a user won't be charged for us repartitioning their data.

To connect to a pod, follow this runbook: [https://runbooks.posthog.com/EKS/access](https://runbooks.posthog.com/EKS/access)

The following code snippet will both disable billing and reset the table - which means deleting all existing table files (other than query files). Make sure to run this on a `temporal-worker-data-warehouse` pod - they have all the correct env vars set up for this:

```python
from posthog.temporal.data_imports.naming_convention import NamingConvention
import os
import s3fs
import time

schema_ids = ['...'] # Schema ID of the tables you want to resync

s3 = s3fs.S3FileSystem()

for index, schema_id in enumerate(schema_ids):
    schema = ExternalDataSchema.objects.get(id=schema_id)
    team_id = schema.team_id
    schema_id = schema.id
    source_id = schema.source.id
    schema_name = NamingConvention.normalize_identifier(schema.name)
    s3_folder = f"{os.environ['BUCKET_URL']}/{schema.folder_path()}/{schema_name}"
    print(f"Deleting {s3_folder}")
    try:
        s3.delete(s3_folder, recursive=True)
    except:
        pass
    print("Starting temporal worker...")
    try:
        os.system('python manage.py start_temporal_workflow external-data-job "{\\"team_id\\": ' + str(team_id) + ',\\"external_data_source_id\\":\\"' + str(source_id) + '\\",\\"external_data_schema_id\\":\\"' + str(schema_id) + '\\",\\"billable\\":false,\\"reset_pipeline\\":true}" --workflow-id ' + str(schema_id) + '-resync-' + str(time.time()) + ' --task-queue data-warehouse-task-queue')
    except Exception as e:
        print(e)
    print(f"{index + 1}/{len(schema_ids)}")
```

If you want to sync a table without resetting it - then the below snippet is for you instead:

```python
from posthog.temporal.data_imports.naming_convention import NamingConvention
import os
import s3fs
import time

schema_ids = ['...'] # Schema ID of the tables you want to resync

s3 = s3fs.S3FileSystem()

for index, schema_id in enumerate(schema_ids):
    schema = ExternalDataSchema.objects.get(id=schema_id)
    team_id = schema.team_id
    schema_id = schema.id
    source_id = schema.source.id
    schema_name = NamingConvention.normalize_identifier(schema.name)
    print("Starting temporal worker...")
    try:
        os.system('python manage.py start_temporal_workflow external-data-job "{\\"team_id\\": ' + str(team_id) + ',\\"external_data_source_id\\":\\"' + str(source_id) + '\\",\\"external_data_schema_id\\":\\"' + str(schema_id) + '\\",\\"billable\\":false,\\"reset_pipeline\\":false}" --workflow-id ' + str(schema_id) + '-resync-' + str(time.time()) + ' --task-queue data-warehouse-task-queue')
    except Exception as e:
        print(e)
    print(f"{index + 1}/{len(schema_ids)}")
```

## How to replay load messages for a stuck/failed job in PipelineV3

When extraction completed but the load consumer failed (OOM, crash, retries exhausted), the parquet files are still in S3. You can replay the Kafka messages to re-trigger just the load phase without re-extracting from the source.

Run this on a `temporal-worker-data-warehouse` pod via `manage.py shell_plus`:

```python
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3 import list_parquet_files, read_parquet
from posthog.temporal.data_imports.pipelines.pipeline_v3.s3.common import get_base_folder, get_data_folder, strip_s3_protocol
from posthog.temporal.data_imports.pipelines.pipeline_v3.kafka.common import ExportSignalMessage, get_warpstream_kafka_producer
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.retry_tracker import clear_retry_info
from posthog.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import is_batch_already_processed
from posthog.kafka_client.topics import KAFKA_WAREHOUSE_SOURCES_JOBS
from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema
from products.data_warehouse.backend.s3 import get_s3_client

schema_id = '...'  # UUID of the schema to replay
dry_run = True  # Set to False to actually send messages
skip_job_check = False  # If True, ignore job status in DB and replay whatever is in S3

schema = ExternalDataSchema.objects.select_related('source').get(id=schema_id)
source = schema.source
team_id = schema.team_id

if skip_job_check:
    # Discover the latest run_uuid folder directly from S3 — strip the trailing run_uuid
    # segment from get_base_folder to get the schema-level prefix
    schema_base = get_base_folder(team_id, str(schema.id), '').rstrip('/')
    schema_prefix = strip_s3_protocol(schema_base)
    s3 = get_s3_client()
    try:
        run_folders = sorted(f.rstrip('/').split('/')[-1] for f in s3.ls(schema_prefix))
    except FileNotFoundError:
        run_folders = []
    if not run_folders:
        print(f"No S3 run folders found under {schema_prefix}")
        job = None
    else:
        run_uuid = run_folders[-1]
        job = ExternalDataJob.objects.filter(schema_id=schema_id, workflow_run_id=run_uuid).order_by('-created_at').first()
        if job is None:
            print(f"Found S3 run_uuid={run_uuid} but no matching ExternalDataJob")
else:
    # Find the latest failed or running job for this schema
    job = (
        ExternalDataJob.objects
        .filter(schema_id=schema_id, status__in=[ExternalDataJob.Status.FAILED, ExternalDataJob.Status.RUNNING])
        .order_by('-created_at')
        .first()
    )

if job is None:
    print(f"No job available for schema {schema_id}")
else:
    run_uuid = job.workflow_run_id
    print(f"Found job {job.id} (status={job.status}, run_uuid={run_uuid})")
    base_folder = get_base_folder(team_id, str(schema.id), run_uuid)
    data_folder = get_data_folder(base_folder)
    parquet_files = list_parquet_files(data_folder)
    if not parquet_files:
        print(f"No parquet files found in {data_folder}")
    else:
        print(f"Found {len(parquet_files)} parquet files in {data_folder}")
    sync_type_config = schema.sync_type_config or {}
    sync_type = schema.sync_type or 'full_refresh'
    if sync_type == 'incremental':
        sync_type_literal = 'incremental'
    elif sync_type == 'append':
        sync_type_literal = 'append'
    else:
        sync_type_literal = 'full_refresh'
    total_rows = 0
    messages = []
    for i, s3_path in enumerate(parquet_files):
        pa_table = read_parquet(s3_path)
        row_count = pa_table.num_rows
        total_rows += row_count
        already_processed = is_batch_already_processed(team_id, str(schema.id), run_uuid, i)
        messages.append({
            'batch_index': i,
            's3_path': s3_path,
            'row_count': row_count,
            'byte_size': pa_table.nbytes,
            'already_processed': already_processed,
        })
        print(f"  batch {i}: {s3_path} ({row_count} rows) {'[SKIP - already processed]' if already_processed else ''}")
    print(f"\nTotal: {len(messages)} batches, {total_rows} rows")
    if not dry_run:
        producer = get_warpstream_kafka_producer()
        # Reset job status
        job.status = ExternalDataJob.Status.RUNNING
        job.latest_error = None
        job.finished_at = None
        job.save()
        print(f"Reset job {job.id} to RUNNING")
        for msg_info in messages:
            # Clear retry info so previously-exhausted retries don't block
            clear_retry_info(team_id, str(schema.id), run_uuid, msg_info['batch_index'])
            is_final = msg_info['batch_index'] == len(messages) - 1
            message = ExportSignalMessage(
                team_id=team_id,
                job_id=str(job.id),
                schema_id=str(schema.id),
                source_id=str(source.id),
                resource_name=schema.name,
                run_uuid=run_uuid,
                batch_index=msg_info['batch_index'],
                s3_path=msg_info['s3_path'],
                row_count=msg_info['row_count'],
                byte_size=msg_info['byte_size'],
                is_final_batch=is_final,
                total_batches=len(messages) if is_final else None,
                total_rows=total_rows if is_final else None,
                sync_type=sync_type_literal,
                data_folder=data_folder if is_final else None,
                schema_path=None,
                primary_keys=sync_type_config.get('primary_keys'),
                is_resume=True,
                partition_count=sync_type_config.get('partition_count'),
                partition_size=sync_type_config.get('partition_size'),
                partition_keys=sync_type_config.get('partition_keys'),
                partition_format=sync_type_config.get('partition_format'),
                partition_mode=sync_type_config.get('partition_mode'),
            )
            key = f"{team_id}:{schema.id}"
            producer.produce(topic=KAFKA_WAREHOUSE_SOURCES_JOBS, data=message.to_dict(), key=key)
        producer.flush()
        print(f"Sent {len(messages)} messages to {KAFKA_WAREHOUSE_SOURCES_JOBS}")
    else:
        print("\nDry run - set dry_run = False to send messages")
```

## How to clean up orphaned S3 data

When a source or schema is soft-deleted, S3 cleanup can fail silently (it's best-effort). This leaves orphaned data in S3 that customers consider deleted.

Run this on a `temporal-worker-data-warehouse` pod to find and delete S3 folders for orphaned schemas:

```python
import os
import s3fs

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

bucket_url = os.environ['BUCKET_URL']
s3 = s3fs.S3FileSystem()

# Find schemas that are soft-deleted but whose S3 folder may still exist
orphaned_schemas = (
    ExternalDataSchema.objects
    .filter(deleted=True)
    .select_related('source')
    .iterator()
)

deleted = 0
skipped = 0
errors = 0

for schema in orphaned_schemas:
    s3_folder = f"{bucket_url}/{schema.folder_path()}"
    try:
        if s3.exists(s3_folder):
            print(f"Deleting {s3_folder} (schema={schema.id}, team={schema.team_id})")
            s3.delete(s3_folder, recursive=True)
            deleted += 1
        else:
            skipped += 1
    except Exception as e:
        print(f"Error deleting {s3_folder}: {e}")
        errors += 1

print(f"Done. Deleted: {deleted}, Already clean: {skipped}, Errors: {errors}")
```

To do a dry run first (just list what would be deleted without actually deleting):

```python
import os
import s3fs

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema

bucket_url = os.environ['BUCKET_URL']
s3 = s3fs.S3FileSystem()

orphaned_schemas = (
    ExternalDataSchema.objects
    .filter(deleted=True)
    .select_related('source')
    .iterator()
)

total_size = 0
count = 0

for schema in orphaned_schemas:
    s3_folder = f"{bucket_url}/{schema.folder_path()}"
    try:
        if s3.exists(s3_folder):
            size = sum(f['size'] for f in s3.ls(s3_folder, detail=True))
            print(f"[WOULD DELETE] {s3_folder} (schema={schema.id}, team={schema.team_id}, size={size / 1024 / 1024:.1f} MB)")
            total_size += size
            count += 1
    except Exception as e:
        print(f"Error checking {s3_folder}: {e}")

print(f"\nTotal: {count} folders, {total_size / 1024 / 1024 / 1024:.2f} GB")
```
