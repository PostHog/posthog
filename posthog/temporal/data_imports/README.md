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

More info on what partitioning options and the different modes can be found here: https://github.com/PostHog/posthog/blob/master/posthog/temporal/data_imports/sources/README.md#partitioning

If a table has the `partition_mode` set to `datetime`, then you'll likely see that `partition_format` is set to either `month` or `None` (which means `month`). To repartition by `day`, you'll want to update this value to `day` and then perform a resync below.

If the `partition_mode` is either `md5` or `numerical`, then you'll want to do a standard resync by following the below instructions.

If the table has no partitions, but it could be partitioned, then again just resync the table following below.

## How to resync

When we resync a table, we do so from a k8s pod. We have the ability to disable billing for a sync via this method meaning that a user won't be charged for us repartitioning their data.

To connect to a pod, follow this runbook: https://runbooks.posthog.com/EKS/access

The following code snippet will both disable billing and reset the table - which means deleting all existing table files (other than query files). Make sure to run this on a `temporal-worker-data-warehouse` pod - they have all the correct env vars set up for this:

```python
from dlt.common.normalizers.naming.snake_case import NamingConvention
import os
import s3fs
import time

schema_ids = ['...'] # Schema ID of the tables you want to resync

s3 = s3fs.S3FileSystem(
    key=os.environ["AIRBYTE_BUCKET_KEY"],
    secret=os.environ["AIRBYTE_BUCKET_SECRET"],
)

for index, schema_id in enumerate(schema_ids):
    schema = ExternalDataSchema.objects.get(id=schema_id)
    team_id = schema.team_id
    schema_id = schema.id
    source_id = schema.source.id
    schema_name = NamingConvention().normalize_identifier(schema.name)
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
from dlt.common.normalizers.naming.snake_case import NamingConvention
import os
import s3fs
import time

schema_ids = ['...'] # Schema ID of the tables you want to resync

s3 = s3fs.S3FileSystem(
    key=os.environ["AIRBYTE_BUCKET_KEY"],
    secret=os.environ["AIRBYTE_BUCKET_SECRET"],
)

for index, schema_id in enumerate(schema_ids):
    schema = ExternalDataSchema.objects.get(id=schema_id)
    team_id = schema.team_id
    schema_id = schema.id
    source_id = schema.source.id
    schema_name = NamingConvention().normalize_identifier(schema.name)
    print("Starting temporal worker...")
    try:
        os.system('python manage.py start_temporal_workflow external-data-job "{\\"team_id\\": ' + str(team_id) + ',\\"external_data_source_id\\":\\"' + str(source_id) + '\\",\\"external_data_schema_id\\":\\"' + str(schema_id) + '\\",\\"billable\\":false,\\"reset_pipeline\\":false}" --workflow-id ' + str(schema_id) + '-resync-' + str(time.time()) + ' --task-queue data-warehouse-task-queue')
    except Exception as e:
        print(e)
    print(f"{index + 1}/{len(schema_ids)}")
```
