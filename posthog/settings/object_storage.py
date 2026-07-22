import os
from typing import Optional

from posthog.settings import get_from_env
from posthog.settings.base_variables import DEBUG, TEST
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

# Notebooks SQLV2 frame store (products/notebooks/backend/sql_v2_frame_store.md): stream
# python-node frame materializations to object storage instead of the Redis JSON transport.
# Default off — rollout is env-gated per deployment on top of the product feature flag.
NOTEBOOKS_FRAME_STORE_ENABLED = get_from_env("NOTEBOOKS_FRAME_STORE_ENABLED", False, type_cast=str_to_bool)

# Query cache specific bucket - falls back to general object storage bucket if not set
QUERY_CACHE_S3_BUCKET = os.getenv("QUERY_CACHE_S3_BUCKET") or OBJECT_STORAGE_BUCKET

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
