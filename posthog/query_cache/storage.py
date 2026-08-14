import time
import pickle
from datetime import timedelta
from typing import Literal, Optional, cast

from django.conf import settings
from django.core.cache import caches
from django.db import DatabaseError, InterfaceError

import zstd
import structlog
from django_redis import get_redis_connection
from redis import Redis, RedisCluster

from posthog.cache_utils import OrjsonJsonSerializer, cache_for
from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS
from posthog.dataclasses import frozen
from posthog.ph_client import get_feature_flag_or_none
from posthog.query_cache.metrics import get_cache_metrics_context
from posthog.storage.object_storage import object_storage_client

logger = structlog.get_logger(__name__)

# Marks a Redis value as an S3 pointer record rather than an entry payload. During a rolling
# deploy, pods running older code can't parse pointer records and treat them as cache misses,
# so an entry written by a new pod may be recomputed once by an old one. Accepted: deploys are
# quick.
S3_POINTER_MAGIC = b"PHQCS3\x00"

# First bytes of a zstd frame and of a pickle protocol 2+ stream. New inline values are bare
# zstd frames; a pickle marker (directly, or inside a zstd frame) identifies a value written
# through django_redis before this module owned the value bytes.
ZSTD_FRAME_MAGIC = b"\x28\xb5\x2f\xfd"
PICKLE_PROTO_MARKER = b"\x80"

# Same floor the django_redis ZstdCompressor uses: below it a zstd frame costs more than it saves.
COMPRESSION_FLOOR_BYTES = 512

# Match the ZstdCompressor settings (preset 0 is zstd's default level, single thread) so inline
# values and S3 blobs compress identically wherever they're produced.
ZSTD_PRESET = 0
ZSTD_THREADS = 1

QueryCacheS3Mode = Literal["off", "shadow", "on"]

# Multivariate flag on the organization group; it gates writes only, the read path never
# evaluates flags. Disabled: every result is stored inline in Redis. "shadow": write the cache
# entry to both S3 and Redis, testing the write path; nothing reads the S3 copy. "on": write
# the pointer to Redis and the entry to S3; reads fetch the blob from S3.
QUERY_CACHE_S3_FLAG = "query-cache-s3-writes"


def _record_s3_write(mode: QueryCacheS3Mode, outcome: str, seconds: Optional[float] = None) -> None:
    # Routed through get_cache_metrics_context because most large results are written from
    # Celery and Temporal, whose short-lived processes only report via the push gateway.
    with get_cache_metrics_context("query_cache_s3") as metrics:
        metrics.s3_write_counter.labels(mode=mode, outcome=outcome).inc()
        if seconds is not None:
            metrics.s3_write_duration.observe(seconds)


def _record_s3_read(outcome: str, seconds: Optional[float] = None) -> None:
    with get_cache_metrics_context("query_cache_s3") as metrics:
        metrics.s3_read_counter.labels(outcome=outcome).inc()
        if seconds is not None:
            metrics.s3_read_duration.observe(seconds)


@frozen
class S3BlobPointer:
    """Location of a cache entry's blob in object storage.

    The bucket is embedded rather than read from settings at resolve time, so entries written
    before a bucket change keep resolving until they expire.
    """

    bucket: str
    key: str


def query_cache_raw_client() -> Redis | RedisCluster:
    return get_redis_connection(QUERY_CACHE_ALIAS)


def entry_redis_key(cache_key: str) -> str:
    # The key django_redis computes for this alias, so entries written before this module owned
    # the value bytes stay addressable, and values this module writes stay on the keys older
    # pods read.
    return caches[QUERY_CACHE_ALIAS].make_key(cache_key)


def load_entry_value(cache_key: str) -> Optional[bytes]:
    return cast(Optional[bytes], query_cache_raw_client().get(entry_redis_key(cache_key)))


def delete_entry(cache_key: str) -> None:
    query_cache_raw_client().delete(entry_redis_key(cache_key))


def _delete_entry_silently(cache_key: str) -> None:
    try:
        delete_entry(cache_key)
    except Exception:
        pass


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
    except (DatabaseError, InterfaceError):
        # Caching is an optimization; a struggling Postgres must not fail the write path.
        # InterfaceError (a dropped connection, e.g. after a pgbouncer recycle) is a sibling of
        # DatabaseError in django.db, not a subclass, so it has to be named separately.
        logger.warning("query_cache_s3_org_lookup_failed", team_id=team_id, exc_info=True)
        return None


def s3_write_mode(team_id: int) -> QueryCacheS3Mode:
    # Without object storage there is nothing to route to: UnavailableStorage swallows writes
    # silently, which would mint pointers to blobs that were never stored.
    if not settings.OBJECT_STORAGE_ENABLED:
        return "off"
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


def encode_stored_value(*, team_id: int, cache_key: str, payload: bytes) -> bytes:
    """The exact bytes to store in Redis for a cache entry: the payload itself (values too small
    to be worth a zstd frame), the zstd-compressed payload, or an S3 pointer record.

    Compression happens here, once; the same compressed bytes serve as the inline Redis value,
    the S3 routing decision, and the S3 upload body.
    """
    if len(payload) <= COMPRESSION_FLOOR_BYTES:
        return payload
    blob = zstd.compress(payload, ZSTD_PRESET, ZSTD_THREADS)
    if len(blob) >= settings.QUERY_CACHE_S3_MIN_COMPRESSED_BYTES:
        mode = s3_write_mode(team_id)
        if mode != "off":
            # "shadow" writes the entry to both S3 and Redis, testing the write path; "on"
            # stores the pointer instead of the blob, so the blob stops counting against the
            # team's Redis cache budget. Upload failures fall back to the inline blob.
            pointer = write_blob(team_id=team_id, cache_key=cache_key, blob=blob, mode=mode)
            if mode == "on" and pointer is not None:
                return pointer
    return blob


def decode_stored_value(value: bytes, *, team_id: int, cache_key: str) -> Optional[bytes]:
    """Resolve stored bytes back to the entry payload. Never raises.

    None means the entry is unusable: definitively dead values (unresolvable pointers, corrupt
    frames) are deleted so subsequent reads miss on the Redis lookup alone, while transient S3
    errors keep the pointer, because the entry becomes readable again once S3 recovers.
    """
    if value.startswith(S3_POINTER_MAGIC):
        return _read_blob(value, team_id=team_id, cache_key=cache_key)
    if value.startswith(ZSTD_FRAME_MAGIC):
        try:
            payload = zstd.decompress(value)
        except zstd.Error:
            logger.warning("query_cache_decompress_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
            _delete_entry_silently(cache_key)
            return None
        return _unpickle_if_legacy(payload, team_id=team_id, cache_key=cache_key)
    if value.startswith(PICKLE_PROTO_MARKER):
        return _unpickle_if_legacy(value, team_id=team_id, cache_key=cache_key)
    return value


def _unpickle_if_legacy(payload: bytes, *, team_id: int, cache_key: str) -> Optional[bytes]:
    """Unwrap values written through django_redis, which pickled entry bytes before storing them.

    Entry payloads themselves never start with the pickle marker (they start with the split-format
    magic or JSON), so the marker uniquely identifies a pre-migration value. Once CACHED_RESULTS_TTL
    has retired every entry written before this module owned the value bytes, this path is dead and
    can be deleted.
    """
    if not payload.startswith(PICKLE_PROTO_MARKER):
        return payload
    try:
        # Only values our own django_redis backend wrote reach this, the same trust that
        # backend's deserialization always placed in this Redis.
        legacy = pickle.loads(payload)
    except Exception:
        logger.warning("query_cache_legacy_unpickle_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        _delete_entry_silently(cache_key)
        return None
    if not isinstance(legacy, bytes):
        logger.warning("query_cache_legacy_value_not_bytes", team_id=team_id, cache_key=cache_key)
        _delete_entry_silently(cache_key)
        return None
    return legacy


def write_blob(*, team_id: int, cache_key: str, blob: bytes, mode: QueryCacheS3Mode) -> Optional[bytes]:
    """Upload a cache entry's compressed blob, returning encoded pointer bytes, or None on failure.

    Never raises: on failure the caller stores the blob inline in Redis, so S3 problems degrade
    to inline caching instead of failing the query response.
    """
    bucket = settings.QUERY_CACHE_S3_BUCKET
    object_key = f"{settings.OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/{cache_key}"
    upload_start = time.perf_counter()
    try:
        # The bucket's lifecycle rule garbage-collects blobs after CACHED_RESULTS_TTL_DAYS;
        # the Redis pointer's TTL is what actually expires the entry. Tags are for attribution
        # only. See docs/internal/workflows/s3-query-cache-setup.md.
        extras = {"Tagging": f"cache_type=query_data&team_id={team_id}"}
        object_storage_client().write(bucket=bucket, key=object_key, content=blob, extras=extras)
    except Exception:
        _record_s3_write(mode, "error", time.perf_counter() - upload_start)
        logger.warning("query_cache_s3_write_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        return None
    _record_s3_write(mode, "success", time.perf_counter() - upload_start)
    return encode_pointer(S3BlobPointer(bucket=bucket, key=object_key))


def _read_blob(pointer_bytes: bytes, *, team_id: int, cache_key: str) -> Optional[bytes]:
    """Resolve a pointer record to the decompressed payload bytes. Never raises."""
    pointer = decode_pointer(pointer_bytes)
    if pointer is None:
        _record_s3_read("corrupt")
        logger.warning("query_cache_s3_pointer_corrupt", team_id=team_id, cache_key=cache_key)
        _delete_entry_silently(cache_key)
        return None
    fetch_start = time.perf_counter()
    try:
        payload = object_storage_client().read_bytes(bucket=pointer.bucket, key=pointer.key, missing_ok=True)
    except Exception:
        _record_s3_read("error", time.perf_counter() - fetch_start)
        logger.warning("query_cache_s3_read_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        return None
    fetch_seconds = time.perf_counter() - fetch_start
    if payload is None:
        _record_s3_read("missing", fetch_seconds)
        _delete_entry_silently(cache_key)
        return None
    try:
        data = zstd.decompress(payload)
    except zstd.Error:
        _record_s3_read("corrupt", fetch_seconds)
        logger.warning("query_cache_s3_decompress_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        _delete_entry_silently(cache_key)
        return None
    _record_s3_read("hit", fetch_seconds)
    return data
