import time
import contextlib
from typing import Optional
from urllib.parse import urlparse

from django.conf import settings

import s3fs
import boto3
import botocore
import botocore.exceptions

from products.data_warehouse.backend.s3_proxy import boto_proxy_config_kwargs


def get_s3_client(*, endpoint_url: Optional[str] = None, skip_instance_cache: bool = False):
    # Defaults for localhost dev and test suites
    if settings.USE_LOCAL_SETUP:
        return s3fs.S3FileSystem(
            key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            secret=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            # skip_instance_cache ensures a fresh S3FileSystem instance is created each time,
            # avoiding "Event loop is closed" errors when the event loop changes between async
            # operations (e.g., between test modules with module-scoped event loops).
            skip_instance_cache=True,
        )

    # config_kwargs reaches botocore's Config; see s3_proxy for why these clients skip the proxy, and
    # why a caller-supplied endpoint_url keeps its traffic on it. endpoint_url is only forwarded when
    # set: fsspec's instance cache keys on the literal kwargs, so passing endpoint_url=None explicitly
    # would split the shared cached client into a second instance.
    #
    # fsspec's instance cache also keys on the calling thread id, so callers invoked from a thread
    # pool (e.g. Temporal's sync-activity executor) get one cached, never-evicted S3FileSystem per
    # thread instead of the single shared instance the caching comment above assumes. skip_instance_cache
    # opts a caller out of that cache entirely for one-off calls where a leaked-forever cache entry
    # (and the open sockets/file handles it holds) isn't worth the connection-reuse it'd otherwise buy.
    extra = {"endpoint_url": endpoint_url} if endpoint_url is not None else {}
    return s3fs.S3FileSystem(
        config_kwargs=boto_proxy_config_kwargs(endpoint_url=endpoint_url),
        skip_instance_cache=skip_instance_cache,
        **extra,
    )


@contextlib.asynccontextmanager
async def aget_s3_client(*, fresh_instance: bool = False, endpoint_url: Optional[str] = None):
    # fresh_instance=True bypasses the fsspec instance cache: a new S3FileSystem bound to the current
    # event loop, closed on context exit. The cached default hands every caller the same instance
    # regardless of loop, so async_to_sync-driven code (each call runs on a fresh, short-lived loop)
    # gets an aiobotocore client bound to an already-closed loop ("Event loop is closed") and a
    # dircache that goes stale whenever delta-rs writes to S3 through its own object store behind
    # s3fs's back. Reserve it for low-frequency, correctness-critical paths (repartition purge/swap):
    # every fresh instance pays connection setup + credential resolution, so defaulting it on would
    # hammer the credential provider from hot paths.
    uncached = fresh_instance or settings.USE_LOCAL_SETUP
    if settings.USE_LOCAL_SETUP:
        # Defaults for localhost dev and test suites. skip_instance_cache avoids "Event loop is
        # closed" errors when the loop changes between test modules.
        s3 = s3fs.S3FileSystem(
            key=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
            secret=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            skip_instance_cache=True,
            asynchronous=True,
        )
    else:
        # endpoint_url only forwarded when set, so the shared cached client isn't split; see
        # get_s3_client and s3_proxy for the proxy-bypass reasoning.
        extra = {"endpoint_url": endpoint_url} if endpoint_url is not None else {}
        s3 = s3fs.S3FileSystem(
            asynchronous=True,
            skip_instance_cache=fresh_instance,
            config_kwargs=boto_proxy_config_kwargs(endpoint_url=endpoint_url),
            **extra,
        )

    await s3.set_session()

    if not uncached:
        yield s3
        return

    try:
        yield s3
    finally:
        # Uncached instances aren't finalized by the fsspec registry, so close the aiobotocore
        # client(s) explicitly (s3fs's set_session docs: "to be closed later with await .close()")
        # to avoid leaking HTTP connections in long-lived workers. Close via _s3creator rather than
        # just _s3: with region caching on (the default), s3fs lazily opens a second, region-specific
        # client the first time a bucket resolves to a different region (S3BucketRegionCache.get_bucket_client),
        # and only _s3creator tracks that second client — closing _s3 alone leaks it. _s3creator's
        # __aexit__ closes everything it opened either way (see s3fs's own close_session, which does
        # the same). Never close the shared cached instance — other callers hold references to it.
        with contextlib.suppress(Exception):
            await s3._s3creator.__aexit__(None, None, None)


def get_size_of_folder(path: str) -> float:
    # skip_instance_cache: this runs from Temporal's sync-activity thread pool, so the shared
    # fsspec cache (keyed by thread id, see get_s3_client) would otherwise leak one S3FileSystem
    # per calling thread forever. A one-off client, closed below, avoids that.
    s3 = get_s3_client(skip_instance_cache=True)

    try:
        files = s3.find(path, detail=True)
        file_values = files.values() if isinstance(files, dict) else files

        total_bytes = sum(f["Size"] for f in file_values if f["type"] != "directory")
        return total_bytes / (1024 * 1024)
    finally:
        with contextlib.suppress(Exception):
            if s3._s3 is not None:
                s3fs.S3FileSystem.close_session(s3.loop, s3._s3creator)


# HeadBucket returns no body on either success or failure, so a 403 from it carries only the HTTP
# status as its "Code" — it can't be told apart from a still-registering local object store (e.g.
# SeaweedFS's credential bootstrap loop, see docker-compose.base.yml) by message here, same ambiguity
# `_is_retryable_purge_error` documents for the sibling HeadObject case. Retry the bounded budget below
# to let that race self-heal; a persistent misconfiguration still raises once it's exhausted.
_HEAD_BUCKET_MAX_ATTEMPTS = 4


def ensure_bucket_exists(s3_url: str, s3_key: str, s3_secret: str, s3_endpoint: Optional[str] = None) -> None:
    try:
        s3_client = boto3.client(
            "s3", aws_access_key_id=s3_key, aws_secret_access_key=s3_secret, endpoint_url=s3_endpoint
        )
    except ValueError as e:
        # botocore refuses to build a client for endpoint hostnames it deems malformed (e.g. a
        # container service name containing an underscore), yet delta-rs's object store — which does
        # the pipeline's actual reads and writes — talks to the same endpoint fine. This bucket check
        # is a best-effort convenience for local/self-hosted setups where the bucket is provisioned
        # out of band, so skip it rather than abort the sync; the storage layer surfaces a real error
        # later if the bucket is genuinely absent.
        if "Invalid endpoint" in str(e):
            return
        raise

    parsed = urlparse(s3_url)
    if parsed.scheme != "s3":
        raise ValueError(f"Invalid S3 URL: {s3_url}")

    bucket_name = parsed.netloc

    attempt = 0
    while True:
        try:
            s3_client.head_bucket(Bucket=bucket_name)
            return
        except botocore.exceptions.ClientError as e:
            error = e.response.get("Error")
            if not error:
                raise

            error_code = error.get("Code")
            if not error_code:
                raise

            if int(error_code) == 404:
                try:
                    s3_client.create_bucket(Bucket=bucket_name)
                except botocore.exceptions.ClientError as create_error:
                    # Concurrent callers can both see the 404 above before either creates the bucket;
                    # the loser's create_bucket then reports it already owns the bucket the winner just
                    # made. That's the intended end state, not a failure.
                    create_error_code = create_error.response.get("Error", {}).get("Code")
                    if create_error_code != "BucketAlreadyOwnedByYou":
                        raise
                return

            if int(error_code) != 403:
                raise

            attempt += 1
            if attempt >= _HEAD_BUCKET_MAX_ATTEMPTS:
                raise
            time.sleep(2**attempt)
