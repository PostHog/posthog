from datetime import timedelta
from typing import Literal, Optional

from django.conf import settings
from django.db import DatabaseError

import zstd
import structlog
from prometheus_client import Counter, Histogram

from posthog.cache_utils import OrjsonJsonSerializer, cache_for
from posthog.dataclasses import frozen
from posthog.ph_client import get_feature_flag_or_none
from posthog.storage.object_storage import object_storage_client

logger = structlog.get_logger(__name__)

# Entries at least QUERY_CACHE_S3_MIN_SIZE_BYTES large can be stored as an S3 object with a
# pointer record left in Redis under the same cache key. The pointer starts with this magic so
# readers can tell it apart from the two blob formats (split-format magic and legacy raw JSON).
# Pods that predate the pointer format fail to parse it and treat the entry as a cache miss,
# which is the same rolling-deploy behavior the split format shipped with.
S3_POINTER_MAGIC = b"PHQCS3\x00"

QueryCacheS3Mode = Literal["off", "shadow", "on"]

# Multivariate flag on the organization group: disabled means off, the "shadow" variant uploads
# blobs while Redis stays authoritative, and the "on" variant stores pointers. Writes only; the
# read path never evaluates flags.
QUERY_CACHE_S3_FLAG = "query-cache-s3-writes"

S3_WRITE_COUNTER = Counter(
    "posthog_query_cache_s3_write_total",
    "Query cache blob uploads to S3, by write mode and outcome.",
    labelnames=["mode", "outcome"],
)

S3_READ_COUNTER = Counter(
    "posthog_query_cache_s3_read_total",
    "Query cache blob reads from S3 pointer entries, by outcome.",
    labelnames=["outcome"],
)

_S3_DURATION_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, float("inf")]

S3_WRITE_DURATION = Histogram(
    "posthog_query_cache_s3_write_duration_seconds",
    "Time spent uploading a query cache blob to S3.",
    buckets=_S3_DURATION_BUCKETS,
)

S3_READ_DURATION = Histogram(
    "posthog_query_cache_s3_read_duration_seconds",
    "Time spent fetching a query cache blob from S3.",
    buckets=_S3_DURATION_BUCKETS,
)


@frozen
class S3BlobPointer:
    """Location of a cache entry's blob in object storage.

    The bucket is embedded rather than read from settings at resolve time, so entries written
    before a bucket change keep resolving until they expire.
    """

    bucket: str
    key: str


@frozen
class S3ReadResult:
    data: Optional[bytes]
    missing: bool = False
    """True when the blob is definitively unreadable (gone or corrupt), so the pointer should be
    dropped. False on transient errors, where keeping the pointer lets reads recover with S3."""


def encode_pointer(pointer: S3BlobPointer) -> bytes:
    return S3_POINTER_MAGIC + OrjsonJsonSerializer({}).dumps({"v": 1, "b": pointer.bucket, "k": pointer.key})


def is_s3_pointer(data: bytes) -> bool:
    return data.startswith(S3_POINTER_MAGIC)


def decode_pointer(data: bytes) -> Optional[S3BlobPointer]:
    if not is_s3_pointer(data):
        return None
    try:
        payload = OrjsonJsonSerializer({}).loads(data[len(S3_POINTER_MAGIC) :])
        return S3BlobPointer(bucket=payload["b"], key=payload["k"])
    except Exception:
        return None


@cache_for(timedelta(minutes=1))
def _organization_id_for_team(team_id: int) -> Optional[str]:
    from posthog.models import Team

    try:
        team = Team.objects.only("organization_id").get(pk=team_id)
        return str(team.organization_id)
    except Team.DoesNotExist:
        return None
    except DatabaseError:
        # Caching is an optimization; a struggling Postgres must not fail the write path.
        logger.warning("query_cache_s3_org_lookup_failed", team_id=team_id, exc_info=True)
        return None


def s3_write_mode(team_id: int) -> QueryCacheS3Mode:
    organization_id = _organization_id_for_team(team_id)
    if organization_id is None:
        return "off"
    variant = get_feature_flag_or_none(
        QUERY_CACHE_S3_FLAG,
        organization_id,
        groups={"organization": organization_id},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    # Only the two known variants activate S3 writes; a boolean flag, an unknown variant, or an
    # evaluation failure all fail closed to the inline Redis path.
    if variant == "shadow":
        return "shadow"
    if variant == "on":
        return "on"
    return "off"


def write_blob(*, team_id: int, cache_key: str, serialized: bytes, mode: QueryCacheS3Mode) -> Optional[bytes]:
    """Compress and upload a cache entry's blob, returning encoded pointer bytes, or None on failure.

    Never raises: the caller stores the blob inline in Redis when this fails, so S3 problems
    degrade to today's behavior instead of failing the query response.
    """
    bucket = settings.QUERY_CACHE_S3_BUCKET
    object_key = f"{settings.OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/{cache_key}"
    try:
        payload = zstd.compress(serialized)
        # The ttl_days tag drives S3 lifecycle rules, which are garbage collection only: the Redis
        # pointer's TTL is what expires the entry. A new ttl_days value still needs a matching
        # lifecycle rule first, or its objects are never deleted; see
        # docs/internal/workflows/s3-query-cache-setup.md.
        extras = {"Tagging": f"ttl_days={settings.CACHED_RESULTS_TTL_DAYS}&cache_type=query_data&team_id={team_id}"}
        with S3_WRITE_DURATION.time():
            object_storage_client().write(bucket=bucket, key=object_key, content=payload, extras=extras)
    except Exception:
        S3_WRITE_COUNTER.labels(mode=mode, outcome="error").inc()
        logger.warning("query_cache_s3_write_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        return None
    S3_WRITE_COUNTER.labels(mode=mode, outcome="success").inc()
    return encode_pointer(S3BlobPointer(bucket=bucket, key=object_key))


def read_blob(pointer_bytes: bytes, *, team_id: int, cache_key: str) -> S3ReadResult:
    """Resolve a pointer record to the decompressed blob bytes. Never raises."""
    pointer = decode_pointer(pointer_bytes)
    if pointer is None:
        S3_READ_COUNTER.labels(outcome="corrupt").inc()
        logger.warning("query_cache_s3_pointer_corrupt", team_id=team_id, cache_key=cache_key)
        return S3ReadResult(data=None, missing=True)
    try:
        with S3_READ_DURATION.time():
            payload = object_storage_client().read_bytes(bucket=pointer.bucket, key=pointer.key, missing_ok=True)
    except Exception:
        S3_READ_COUNTER.labels(outcome="error").inc()
        logger.warning("query_cache_s3_read_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        return S3ReadResult(data=None, missing=False)
    if payload is None:
        S3_READ_COUNTER.labels(outcome="missing").inc()
        return S3ReadResult(data=None, missing=True)
    try:
        data = zstd.decompress(payload)
    except zstd.Error:
        S3_READ_COUNTER.labels(outcome="corrupt").inc()
        logger.warning("query_cache_s3_decompress_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        return S3ReadResult(data=None, missing=True)
    S3_READ_COUNTER.labels(outcome="hit").inc()
    return S3ReadResult(data=data)
