"""The bytes stored in Redis for each query cache entry.

encode_inline_value picks the bytes stored inline for a serialized result;
schedule_upload_for_pointer uploads large frames to S3 in the background and swaps in the
pointer record that replaces them in Redis; decode_stored_value turns stored bytes back into
the result. Everything else serves those.

A Redis value is a bare byte string shared with older pods during rolling deploys, so each
storage format announces itself in its first bytes:

- S3_POINTER_MAGIC: a small pointer record naming the S3 bucket and key that hold the
  zstd-compressed result, plus the result's last_refresh so freshness probes stay a single
  Redis read. Written for large results when the team's rollout flag is on.
- ZSTD_FRAME_MAGIC: the zstd-compressed result, stored inline. The default format for
  results over COMPRESSION_FLOOR_BYTES.
- PICKLE_PROTO_MARKER: a result pickled by django_redis before this module owned the value
  bytes, sometimes inside a zstd frame. Read but never written; these entries disappear as
  CACHED_RESULTS_TTL retires them, and the legacy path at the bottom goes with them.
- No marker: the result as-is, for values too small to be worth a zstd frame.

Sniffing is unambiguous because results start with JSON or QUERY_CACHE_SPLIT_MAGIC, never
with a marker. A pod whose code predates a format cannot read it: it logs a read error,
deletes the entry, and recomputes. Its rewrite is readable by every version, so a
mixed-version deploy costs at most one extra recompute per entry.
"""

import io
import time
import pickle
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Literal, NoReturn, Optional, cast
from uuid import uuid4

from django.conf import settings
from django.core.cache import caches

import zstd
import structlog
from django_redis import get_redis_connection
from prometheus_client import Counter, Histogram
from redis import Redis, RedisCluster

from posthog.cache_utils import OrjsonJsonSerializer, cache_for
from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS
from posthog.dataclasses import frozen
from posthog.ph_client import get_feature_flag_or_none
from posthog.storage.object_storage import object_storage_client

logger = structlog.get_logger(__name__)

# Format markers. S3_POINTER_MAGIC is this module's own; the other two are fixed by the
# zstd frame format and pickle protocol 2+.
S3_POINTER_MAGIC = b"PHQCS3\x00"
ZSTD_FRAME_MAGIC = b"\x28\xb5\x2f\xfd"
PICKLE_PROTO_MARKER = b"\x80"

# Mirror the django_redis ZstdCompressor: the same floor (below it a zstd frame costs more
# than it saves) and the same settings (preset 0 is zstd's default level, single thread),
# so inline values and S3 blobs compress identically wherever they're produced.
COMPRESSION_FLOOR_BYTES = 512
ZSTD_PRESET = 0
ZSTD_THREADS = 1

QueryCacheS3Mode = Literal["off", "shadow", "on"]

# Multivariate flag on the organization group, evaluated on writes only; the read path never
# touches flags. "shadow" writes the entry to both S3 and Redis to prove out the write path
# while reads keep using the Redis copy; "on" stores the pointer in Redis and the entry in S3.
QUERY_CACHE_S3_FLAG = "query-cache-s3-writes"

# On the default registry, not get_cache_metrics_context: Celery and Temporal workers already
# serve scrape endpoints, and the push gateway replaces the whole job on every push, which
# would collapse these per-call counters and histograms to the latest observation.
S3_WRITE_COUNTER = Counter(
    name="posthog_query_cache_s3_write_total",
    documentation="Query cache blob uploads to S3, by write mode and outcome.",
    labelnames=["mode", "outcome"],
)

S3_READ_COUNTER = Counter(
    name="posthog_query_cache_s3_read_total",
    documentation="Query cache blob reads from S3 pointer entries, by outcome.",
    labelnames=["outcome"],
)

# Buckets start at 50ms because only large blobs make the trip, and reach tens of seconds for
# multi-MB transfers. Failures return fast (1s connect and 5s idle-socket timeouts, no
# retries), so durations carry outcome labels; folded into one series an S3 outage would make
# latency look better, not worse.
_S3_DURATION_BUCKETS = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf")]

S3_WRITE_DURATION = Histogram(
    name="posthog_query_cache_s3_write_duration_seconds",
    documentation="Time spent uploading a query cache blob to S3, by write mode and outcome.",
    labelnames=["mode", "outcome"],
    buckets=_S3_DURATION_BUCKETS,
)

S3_READ_DURATION = Histogram(
    name="posthog_query_cache_s3_read_duration_seconds",
    documentation="Time spent fetching a query cache blob from S3, by outcome.",
    labelnames=["outcome"],
    buckets=_S3_DURATION_BUCKETS,
)

S3_WRITE_BYTES_COUNTER = Counter(
    name="posthog_query_cache_s3_write_bytes_total",
    documentation="Compressed bytes uploaded to S3, by write mode; the growth signal for the bucket.",
    labelnames=["mode"],
)

S3_DELETE_COUNTER = Counter(
    name="posthog_query_cache_s3_delete_total",
    documentation="Query cache blob deletes, by what orphaned the blob and outcome.",
    labelnames=["trigger", "outcome"],
)

LEGACY_VALUE_READ_COUNTER = Counter(
    name="posthog_query_cache_legacy_value_read_total",
    documentation="Successful reads of values written through django_redis before this module "
    "owned the value bytes; the legacy unpickling path is deletable once this stays at zero.",
)


def _record_s3_write(mode: QueryCacheS3Mode, outcome: str, seconds: Optional[float] = None) -> None:
    S3_WRITE_COUNTER.labels(mode=mode, outcome=outcome).inc()
    if seconds is not None:
        S3_WRITE_DURATION.labels(mode=mode, outcome=outcome).observe(seconds)


def _record_s3_read(outcome: str, seconds: Optional[float] = None) -> None:
    S3_READ_COUNTER.labels(outcome=outcome).inc()
    if seconds is not None:
        S3_READ_DURATION.labels(outcome=outcome).observe(seconds)


def query_cache_raw_client() -> Redis | RedisCluster:
    return get_redis_connection(QUERY_CACHE_ALIAS)


def query_cache_read_client() -> Redis | RedisCluster:
    # write=False keeps reads on the reader replica, as the replaced caches[alias].get() did;
    # the default write client would shift the cache's full read load onto the primary.
    return get_redis_connection(QUERY_CACHE_ALIAS, write=False)


def entry_redis_key(cache_key: str) -> str:
    # The key django_redis computes for this alias, so entries written before this module owned
    # the value bytes stay addressable, and values this module writes stay on the keys older
    # pods read.
    return caches[QUERY_CACHE_ALIAS].make_key(cache_key)


def load_entry_value(cache_key: str) -> Optional[bytes]:
    return cast(Optional[bytes], query_cache_read_client().get(entry_redis_key(cache_key)))


def delete_entry(cache_key: str) -> None:
    query_cache_raw_client().delete(entry_redis_key(cache_key))


def encode_inline_value(payload: bytes) -> bytes:
    """The bytes stored inline in Redis for a serialized result: the payload or its zstd frame.

    Compression happens here, once: the same frame serves as the inline value, the S3 routing
    decision, and the S3 upload body.
    """
    # USE_REDIS_COMPRESSION is the fleet-wide compression kill switch; skipping the frame also
    # keeps the value off the S3 route, which only takes zstd frames.
    if len(payload) <= COMPRESSION_FLOOR_BYTES or not settings.USE_REDIS_COMPRESSION:
        return payload
    return zstd.compress(payload, ZSTD_PRESET, ZSTD_THREADS)


# Bounds the blob bytes held by queued uploads while S3 is slow or down; a skipped upload is
# safe because the entry is already stored inline.
_UPLOAD_MAX_PENDING = 8

_upload_slots = threading.Semaphore(_UPLOAD_MAX_PENDING)
_upload_executor: Optional[ThreadPoolExecutor] = None
_upload_executor_lock = threading.Lock()


def _get_upload_executor() -> ThreadPoolExecutor:
    # Created on first use so the threads start in the serving process, not in a pre-fork
    # parent whose threads would not survive the fork.
    global _upload_executor
    if _upload_executor is None:
        with _upload_executor_lock:
            if _upload_executor is None:
                _upload_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="query-cache-s3")
    return _upload_executor


def schedule_upload_for_pointer(
    *,
    team_id: int,
    cache_key: str,
    inline_value: bytes,
    last_refresh: Optional[str],
    swap: Callable[[bytes], bool],
) -> None:
    """Upload an already-stored inline value to S3 off the calling thread, then swap(pointer).

    Only zstd frames of at least QUERY_CACHE_S3_MIN_COMPRESSED_BYTES route to S3, gated by the
    team's flag. "shadow" uploads without swapping, so Redis keeps the blob; "on" swaps in the
    pointer once the upload succeeded, so the blob stops counting against the team's Redis
    cache budget. The write mode resolves on the calling thread because it touches Postgres
    and Django closes connections per request, not per worker thread. Never raises, and the
    caller never waits on S3: with the pool saturated the upload is skipped and the entry
    simply stays inline.
    """
    if (
        not inline_value.startswith(ZSTD_FRAME_MAGIC)
        or len(inline_value) < settings.QUERY_CACHE_S3_MIN_COMPRESSED_BYTES
    ):
        return
    mode = s3_write_mode(team_id)
    if mode == "off":
        return
    if not _upload_slots.acquire(blocking=False):
        _record_s3_write(mode, "saturated")
        return

    def _upload_and_swap() -> None:
        try:
            pointer = write_blob(
                team_id=team_id, cache_key=cache_key, blob=inline_value, mode=mode, last_refresh=last_refresh
            )
            if mode == "on" and pointer is not None:
                swapped = swap(pointer)
                if not swapped:
                    logger.info("query_cache_s3_swap_superseded", team_id=team_id, cache_key=cache_key)
                    superseded = decode_pointer(pointer)
                    if superseded is not None:
                        # This upload's blob never entered Redis, so no reader can hold its
                        # pointer; delete immediately rather than through the delayed task.
                        delete_blob(bucket=superseded.bucket, key=superseded.key, team_id=team_id, trigger="superseded")
        except Exception:
            logger.warning("query_cache_s3_swap_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        finally:
            _upload_slots.release()

    try:
        _get_upload_executor().submit(_upload_and_swap)
    except Exception:
        _upload_slots.release()
        logger.warning("query_cache_s3_upload_submit_failed", team_id=team_id, cache_key=cache_key, exc_info=True)


def decode_stored_value(value: bytes, *, team_id: int, cache_key: str) -> Optional[bytes]:
    """Resolve stored bytes back to the result payload. Never raises, never mutates.

    None means this read found the entry unusable (corrupt bytes, an unresolvable pointer).
    The miss sends the caller to recompute, and its store overwrites the entry, so dead
    entries heal by replacement rather than by deletion here.
    """
    if is_s3_pointer(value):
        return _read_blob(value, team_id=team_id, cache_key=cache_key)
    if value.startswith(ZSTD_FRAME_MAGIC):
        try:
            payload = zstd.decompress(value)
        except Exception:
            # Broader than zstd.Error on purpose: a corrupt frame's declared content size
            # raises MemoryError or OverflowError, and this function must never raise.
            logger.warning("query_cache_decompress_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
            return None
        return _unpickle_if_legacy(payload, team_id=team_id, cache_key=cache_key)
    if value.startswith(PICKLE_PROTO_MARKER):
        return _unpickle_if_legacy(value, team_id=team_id, cache_key=cache_key)
    return value


@frozen
class S3BlobPointer:
    """Location of a cache entry's blob in object storage, plus the result's last_refresh.

    The bucket is embedded rather than read from settings at resolve time, so entries written
    before a bucket change keep resolving until they expire. last_refresh rides along so
    freshness probes (cache warming) can answer from Redis without fetching the blob.
    """

    bucket: str
    key: str
    last_refresh: Optional[str] = None


def encode_pointer(pointer: S3BlobPointer) -> bytes:
    record: dict[str, str | int] = {"v": 1, "b": pointer.bucket, "k": pointer.key}
    if pointer.last_refresh is not None:
        record["lr"] = pointer.last_refresh
    return S3_POINTER_MAGIC + OrjsonJsonSerializer({}).dumps(record)


def is_s3_pointer(data: bytes) -> bool:
    return data.startswith(S3_POINTER_MAGIC)


def decode_pointer(data: bytes) -> Optional[S3BlobPointer]:
    if not is_s3_pointer(data):
        return None
    try:
        payload = OrjsonJsonSerializer({}).loads(data[len(S3_POINTER_MAGIC) :])
        # An unrecognized version or shape must read as corrupt (miss + recompute), not decode
        # into a bogus pointer that is retried against S3.
        if payload.get("v") != 1 or not isinstance(payload.get("b"), str) or not isinstance(payload.get("k"), str):
            return None
        last_refresh = payload.get("lr")
        return S3BlobPointer(
            bucket=payload["b"],
            key=payload["k"],
            last_refresh=last_refresh if isinstance(last_refresh, str) else None,
        )
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
    except Exception:
        # Caching is an optimization: a failure here (struggling Postgres, dropped pgbouncer
        # connection, anything unexpected) must degrade to the inline path, not abort the write.
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
        # Local evaluation only sees properties supplied here, so an id-filtered rollout needs
        # the id or it evaluates inconclusive and reads as off. Filters on any other
        # organization property still read as off.
        group_properties={"organization": {"id": organization_id}},
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


def write_blob(
    *, team_id: int, cache_key: str, blob: bytes, mode: QueryCacheS3Mode, last_refresh: Optional[str] = None
) -> Optional[bytes]:
    """Upload a cache entry's compressed blob, returning encoded pointer bytes, or None on failure.

    Never raises: on failure the caller stores the blob inline in Redis, so S3 problems degrade
    to inline caching instead of failing the query response.
    """
    bucket = settings.QUERY_CACHE_S3_BUCKET
    # A fresh object per upload: overlapping recomputes of one query would otherwise race on a
    # shared key, and the last PUT to land could pair an older blob with a newer pointer's
    # metadata. Superseded generations become unreferenced objects the lifecycle rule collects.
    object_key = f"{settings.OBJECT_STORAGE_S3_QUERY_CACHE_FOLDER}/{team_id}/{cache_key}/{uuid4().hex}"
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
    S3_WRITE_BYTES_COUNTER.labels(mode=mode).inc(len(blob))
    return encode_pointer(S3BlobPointer(bucket=bucket, key=object_key, last_refresh=last_refresh))


# A reader resolves a pointer in two steps, the Redis GET and then the S3 fetch, with
# milliseconds between them. Delaying the delete far past that window means a reader holding
# a just-replaced pointer still completes its read instead of turning into a recompute.
BLOB_DELETE_DELAY_SECONDS = 60


def delete_blob(*, bucket: str, key: str, team_id: int, trigger: str) -> None:
    """Best-effort delete of a blob nothing references anymore. Never raises: a blob that
    outlives its pointer is only a storage cost, and the bucket's lifecycle rule collects
    whatever this misses."""
    try:
        object_storage_client().delete(bucket=bucket, key=key)
    except Exception:
        S3_DELETE_COUNTER.labels(trigger=trigger, outcome="error").inc()
        logger.warning("query_cache_s3_delete_failed", team_id=team_id, bucket=bucket, key=key, exc_info=True)
        return
    S3_DELETE_COUNTER.labels(trigger=trigger, outcome="success").inc()


def schedule_blob_delete(old_value: object, *, team_id: int, cache_key: str, trigger: str) -> None:
    """Enqueue a delayed best-effort delete for the blob behind a pointer that just left Redis.

    Callers pass a displacing script's raw return value; anything that isn't a pointer
    record is ignored. Never raises: cache writes happen in web, Celery, Temporal, and
    Dagster processes, and one of them failing to reach the broker must cost an orphaned
    blob (the lifecycle rule collects it), not the cache write.
    """
    if not isinstance(old_value, bytes) or not is_s3_pointer(old_value):
        return
    pointer = decode_pointer(old_value)
    if pointer is None:
        return
    try:
        from posthog.query_cache.tasks import (
            delete_query_cache_blob,  # noqa: PLC0415 — circular: tasks.py imports this module
        )

        delete_query_cache_blob.apply_async(
            kwargs={"bucket": pointer.bucket, "key": pointer.key, "team_id": team_id, "trigger": trigger},
            countdown=BLOB_DELETE_DELAY_SECONDS,
        )
    except Exception:
        logger.warning("query_cache_s3_delete_enqueue_failed", team_id=team_id, cache_key=cache_key, exc_info=True)


def _read_blob(pointer_bytes: bytes, *, team_id: int, cache_key: str) -> Optional[bytes]:
    """Resolve a pointer record to the decompressed payload bytes. Never raises."""
    pointer = decode_pointer(pointer_bytes)
    if pointer is None:
        _record_s3_read("pointer_corrupt")
        logger.warning("query_cache_s3_pointer_corrupt", team_id=team_id, cache_key=cache_key)
        return None
    if not settings.OBJECT_STORAGE_ENABLED:
        # UnavailableStorage would report these reads as "missing", which looks like data
        # loss during a deliberate storage rollback; label them for what they are.
        _record_s3_read("storage_disabled")
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
        return None
    try:
        data = zstd.decompress(payload)
    except Exception:
        # Broader than zstd.Error on purpose: a corrupt frame's declared content size raises
        # MemoryError or OverflowError, and this function must never raise.
        _record_s3_read("blob_corrupt", fetch_seconds)
        logger.warning("query_cache_s3_decompress_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        return None
    _record_s3_read("hit", fetch_seconds)
    return data


class _LegacyValueUnpickler(pickle.Unpickler):
    """django_redis pickled entry values as plain bytes objects, which never reference a global,
    so any attempt to resolve one marks a crafted value rather than a legacy entry."""

    def find_class(self, module: str, name: str) -> NoReturn:
        # ValueError rather than pickle.UnpicklingError: the caller catches broadly, and the
        # qualified call trips the same semgrep rule this class exists to satisfy.
        raise ValueError(f"legacy cache value must not reference {module}.{name}")


def _unpickle_if_legacy(payload: bytes, *, team_id: int, cache_key: str) -> Optional[bytes]:
    """Unwrap a value that django_redis pickled before this module owned the value bytes.

    Deletable once CACHED_RESULTS_TTL has retired every entry written through django_redis.
    """
    if not payload.startswith(PICKLE_PROTO_MARKER):
        return payload
    try:
        legacy = _LegacyValueUnpickler(io.BytesIO(payload)).load()
    except Exception:
        logger.warning("query_cache_legacy_unpickle_failed", team_id=team_id, cache_key=cache_key, exc_info=True)
        return None
    if not isinstance(legacy, bytes):
        logger.warning("query_cache_legacy_value_not_bytes", team_id=team_id, cache_key=cache_key)
        return None
    LEGACY_VALUE_READ_COUNTER.inc()
    return legacy
