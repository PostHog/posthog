import os
from typing import Optional

from posthog.settings.base_variables import DEBUG, TEST
from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool

if TEST or DEBUG:
    OBJECT_STORAGE_ENDPOINT = os.getenv("OBJECT_STORAGE_ENDPOINT", "http://objectstorage:19000")
    OBJECT_STORAGE_ACCESS_KEY_ID: Optional[str] = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID", "object_storage_root_user")
    OBJECT_STORAGE_SECRET_ACCESS_KEY: Optional[str] = os.getenv(
        "OBJECT_STORAGE_SECRET_ACCESS_KEY", "object_storage_root_password"
    )
else:
    OBJECT_STORAGE_ENDPOINT = os.getenv("OBJECT_STORAGE_ENDPOINT", "")
    # To enable us to specify that the AWS provided credentials for e.g. the EC2
    # or Fargate task, we default to `None` rather than "" as this will, when
    # passed to boto, result in the correct credentials being used.
    OBJECT_STORAGE_ACCESS_KEY_ID = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID", "") or None
    OBJECT_STORAGE_SECRET_ACCESS_KEY = os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "") or None

OBJECT_STORAGE_ENABLED = get_from_env("OBJECT_STORAGE_ENABLED", True if DEBUG else False, type_cast=str_to_bool)
OBJECT_STORAGE_PUBLIC_ENDPOINT = os.getenv("OBJECT_STORAGE_PUBLIC_ENDPOINT", "") or OBJECT_STORAGE_ENDPOINT
OBJECT_STORAGE_REGION = os.getenv("OBJECT_STORAGE_REGION", "us-east-1")
OBJECT_STORAGE_BUCKET = os.getenv("OBJECT_STORAGE_BUCKET", "posthog")
OBJECT_STORAGE_TRANSFER_ACCELERATION = get_from_env(
    "OBJECT_STORAGE_TRANSFER_ACCELERATION", False, type_cast=str_to_bool
)
OBJECT_STORAGE_EXPORTS_FOLDER = os.getenv("OBJECT_STORAGE_EXPORTS_FOLDER", "exports")
OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER = os.getenv("OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER", "media_uploads")
OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER = os.getenv(
    "OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER", "symbolsets"
)
OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER = os.getenv("OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER", "query_cache")
OBJECT_STORAGE_TASKS_FOLDER = os.getenv("OBJECT_STORAGE_TASKS_FOLDER", "tasks")
OBJECT_STORAGE_LEGAL_DOCUMENTS_FOLDER = os.getenv("OBJECT_STORAGE_LEGAL_DOCUMENTS_FOLDER", "legal_documents")
OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET = os.getenv("OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET", "posthog")

# Endpoint the ClickHouse *cluster* uses to reach the frames bucket for that INSERT — which is
# NOT always OBJECT_STORAGE_ENDPOINT. CI points OBJECT_STORAGE_ENDPOINT at localhost:19000 for
# the test process, but ClickHouse runs in docker-compose and reaches object storage by service
# name (objectstorage:19000) — using localhost there makes the cluster connect to itself and the
# s3() call hangs. So in TEST/DEBUG default to the cluster-reachable host; on prod it stays empty
# and the URL builder falls back to the virtual-hosted AWS form (IAM role, no inline keys),
# mirroring IDENTITY_MATCHING_S3_ENDPOINT (the sibling CH-side s3 writer). Frames live in
# NOTEBOOKS_FRAME_STORE_S3_BUCKET (below), which the app presigns and the kernel fetches from.
if TEST or DEBUG:
    NOTEBOOKS_FRAME_STORE_S3_ENDPOINT = os.getenv("NOTEBOOKS_FRAME_STORE_S3_ENDPOINT", "http://objectstorage:19000")
else:
    NOTEBOOKS_FRAME_STORE_S3_ENDPOINT = os.getenv("NOTEBOOKS_FRAME_STORE_S3_ENDPOINT", "")

# Frames get a dedicated bucket in cloud (its own 1-day TTL, and a least-privilege grant so the
# ClickHouse writer identity can PutObject there without access to the general object store).
# Falls back to OBJECT_STORAGE_BUCKET so dev / CI / self-hosted work with no extra config.
#
# There is deliberately no region knob beside it. ClickHouse writes the object and the app
# presigns it, and the app's presigning client is built once from OBJECT_STORAGE_REGION — so a
# frames-only region would put the write in one region and the SigV4 credential scope in
# another, and AWS would reject every presigned fetch. The bucket is per product; the region is
# per deployment.
NOTEBOOKS_FRAME_STORE_S3_BUCKET = os.getenv("NOTEBOOKS_FRAME_STORE_S3_BUCKET") or OBJECT_STORAGE_BUCKET

# Query cache specific bucket - falls back to general object storage bucket if not set
QUERY_CACHE_S3_BUCKET = os.getenv("QUERY_CACHE_S3_BUCKET") or OBJECT_STORAGE_BUCKET

# Entries whose zstd-compressed form is at least this large go to S3 (with a Redis pointer) when
# the query-cache-s3-writes flag allows; smaller ones always stay inline in Redis. The threshold
# applies to compressed bytes because that is what an entry actually costs in Redis. Query results
# compress roughly 3-15x, so the 128KB default corresponds to about 0.4-2MB of serialized JSON:
# dashboard tiles, which almost never reach that size, stay on sub-millisecond Redis reads while
# the byte-heavy tail of ad-hoc and API results moves off the cluster.
QUERY_CACHE_S3_MIN_COMPRESSED_BYTES = get_from_env("QUERY_CACHE_S3_MIN_COMPRESSED_BYTES", 128 * 1024, type_cast=int)

# Video segment clustering workflow bucket - should have a 24h lifecycle rule for automatic cleanup
VIDEO_SEGMENT_CLUSTERING_S3_BUCKET = os.getenv("VIDEO_SEGMENT_CLUSTERING_S3_BUCKET") or OBJECT_STORAGE_BUCKET

# Billing usage report bucket — holds the daily JSONL chunks the billing
# service consumes. Falls back to the general bucket if not set so dev /
# self-hosted continue to work without extra configuration.
BILLING_USAGE_REPORTS_S3_BUCKET = os.getenv("BILLING_USAGE_REPORTS_S3_BUCKET") or OBJECT_STORAGE_BUCKET

# Agent platform bundle bucket — stores `ass deploy` bundles. Lifecycle should
# expire non-`ready` bundles after a grace period (handled by infra). Falls
# back to the general bucket in dev / self-hosted.
AGENT_BUNDLES_S3_BUCKET = os.getenv("AGENT_BUNDLES_S3_BUCKET") or OBJECT_STORAGE_BUCKET

# AI observability blob storage — offloaded binary payloads (images, files) from ai_events,
# content-addressed under `{prefix}{team_id}/sha256/{hash}`. The nodejs ingestion writer reads
# the same AI_BLOB_S3_BUCKET / AI_BLOB_S3_PREFIX env vars but defaults both to "" (offload
# disabled) — any deployment enabling offload must set bucket AND prefix identically on both
# services, or every read silently 404s. Defaults here match the local-dev ingestion wiring.
AI_BLOB_S3_BUCKET = os.getenv("AI_BLOB_S3_BUCKET", "ai-blobs")
AI_BLOB_S3_PREFIX = os.getenv("AI_BLOB_S3_PREFIX", "aio/")

# Inbox ranking modeling dataset (products/signals/dags/inbox_ranking): daily report-grain
# Parquet snapshots the ranking model trains on. Unset bucket on Cloud means the dags skip until
# the dedicated bucket is provisioned; local dev falls back to the object-storage service. The
# bucket is written by Dagster via boto3 (node role on prod) and read by project-2 warehouse
# tables and mlhog training via a separate read-only credential.
INBOX_RANKING_DATASET_S3_BUCKET = os.getenv("INBOX_RANKING_DATASET_S3_BUCKET", "")
INBOX_RANKING_DATASET_S3_PREFIX = os.getenv("INBOX_RANKING_DATASET_S3_PREFIX", "inbox_ranking")
# Training dag (products/signals/dags/inbox_ranking/training): how many daily snapshots back the
# examples reach, how many trailing days of reports grade a candidate, and whether a winning
# candidate rewrites the champion pointer on its own. Promotion stays manual until the first shadow
# read has a frozen champion to read against; the candidate is still trained and graded daily.
INBOX_RANKING_TRAINING_LOOKBACK_DAYS = get_from_env("INBOX_RANKING_TRAINING_LOOKBACK_DAYS", 60, type_cast=int)
INBOX_RANKING_TRAINING_HOLDOUT_DAYS = get_from_env("INBOX_RANKING_TRAINING_HOLDOUT_DAYS", 7, type_cast=int)
INBOX_RANKING_AUTO_PROMOTE = get_from_env("INBOX_RANKING_AUTO_PROMOTE", False, type_cast=str_to_bool)
INBOX_RANKING_PROMOTION_MIN_DAYS = get_from_env("INBOX_RANKING_PROMOTION_MIN_DAYS", 3, type_cast=int)

# Identity matching scratch storage (products/growth `identity_matching_job`). The job writes
# per-run Parquet objects via ClickHouse `INSERT INTO FUNCTION s3(...)` and the read API globs
# them back with `s3(...)`, so only the ClickHouse cluster needs bucket access — the Dagster
# process and the web process never touch boto3. Retention is owned by the bucket lifecycle
# policy (there is no MergeTree TTL on S3); infra must expire the prefix (≥ the eval horizon so
# a run's inputs survive until evaluation). Prod bucket names are infra-provided via env and
# never committed; local/dev/test reuse the object-storage service (SeaweedFS).
IDENTITY_MATCHING_S3_BUCKET = os.getenv("IDENTITY_MATCHING_S3_BUCKET") or OBJECT_STORAGE_BUCKET
IDENTITY_MATCHING_S3_PREFIX = os.getenv("IDENTITY_MATCHING_S3_PREFIX", "identity_matching")
IDENTITY_MATCHING_S3_REGION = os.getenv("IDENTITY_MATCHING_S3_REGION") or OBJECT_STORAGE_REGION
# Endpoint is set for S3-compatible object storage (local/dev/test); empty on prod, where the
# cluster reaches the bucket over AWS S3 via its attached IAM role (so no endpoint and no keys
# — the credential question is owned by infra, mirroring events_backfill_to_duckling).
#
# This must be the endpoint the ClickHouse *cluster* can reach, which is not always
# OBJECT_STORAGE_ENDPOINT: CI points OBJECT_STORAGE_ENDPOINT at `localhost:19000` for the test
# process, but ClickHouse runs in docker-compose and reaches object storage by its service name
# (`objectstorage:19000`) — using `localhost` there makes the cluster connect to itself and the
# s3() call hangs. So in TEST/DEBUG default to the cluster-reachable host (matching the
# `objectstorage:19000` convention in data_warehouse / web_analytics_s3); on prod it stays empty.
if TEST or DEBUG:
    IDENTITY_MATCHING_S3_ENDPOINT: Optional[str] = (
        os.getenv("IDENTITY_MATCHING_S3_ENDPOINT", "http://objectstorage:19000") or None
    )
else:
    IDENTITY_MATCHING_S3_ENDPOINT = os.getenv("IDENTITY_MATCHING_S3_ENDPOINT", "") or None

# Deletion dictionary staging (posthog/dags/deletes.py). The pending-deletion and queued-uuid
# dictionaries reach every host of the main cluster because their source table is replicated, and
# replication is exactly what stops at a cluster boundary: a cluster with its own Keeper can never
# join that replica set. So when a deletion target's storage lives on another cluster, deletes_job
# stages the dictionary rows here as Parquet and each host there loads the same object for itself.
# Written and read by the ClickHouse cluster via `INSERT INTO FUNCTION s3(...)` / `s3(...)`, so
# only the cluster needs bucket access; the Dagster process never touches boto3. Nothing deletes
# these objects, so infra must expire the prefix through the bucket lifecycle policy. They hold
# team ids and the person uuids already recorded on the Postgres AsyncDeletion rows.
DELETES_DICTIONARY_S3_BUCKET = os.getenv("DELETES_DICTIONARY_S3_BUCKET") or OBJECT_STORAGE_BUCKET
DELETES_DICTIONARY_S3_PREFIX = os.getenv("DELETES_DICTIONARY_S3_PREFIX", "deletes_dictionaries")
DELETES_DICTIONARY_S3_REGION = os.getenv("DELETES_DICTIONARY_S3_REGION") or OBJECT_STORAGE_REGION
# Must be an endpoint the ClickHouse cluster can reach, which is not always OBJECT_STORAGE_ENDPOINT;
# see the IDENTITY_MATCHING_S3_ENDPOINT note above for why localhost breaks under TEST.
if TEST or DEBUG:
    DELETES_DICTIONARY_S3_ENDPOINT: Optional[str] = (
        os.getenv("DELETES_DICTIONARY_S3_ENDPOINT", "http://objectstorage:19000") or None
    )
else:
    DELETES_DICTIONARY_S3_ENDPOINT = os.getenv("DELETES_DICTIONARY_S3_ENDPOINT", "") or None
