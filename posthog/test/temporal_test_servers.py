"""Download Temporal's ephemeral test servers with retries before tests start them.

`WorkflowEnvironment.start_time_skipping()` and `start_local()` download their server
binary on first use. The SDK downloads it once per call with no retry and no read timeout,
so a flaky network fails the test or hangs it until the job timeout. This module downloads the binaries
with timeouts and retries into a per-SDK-version cache directory, under a file lock so
parallel pytest processes download each binary once. It then passes the cached path to
the SDK as `*_existing_path`. If every attempt fails, the test fails with
`TemporalServerDownloadError` instead of falling back to the SDK download, because that
download can hang until the job timeout. A binary that the SDK downloaded earlier still
works without network access.
"""

from __future__ import annotations

import os
import sys
import gzip
import time
import uuid
import zlib
import shutil
import asyncio
import logging
import tarfile
import platform
import tempfile
import functools
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import requests
import temporalio.service
from filelock import FileLock, Timeout
from temporalio.testing import WorkflowEnvironment

from posthog.dataclasses import frozen

logger = logging.getLogger(__name__)

DOWNLOAD_BASE_URL = "https://temporal.download"
TEMPORAL_ASSETS_URL = f"{DOWNLOAD_BASE_URL}/assets/"
GITHUB_URL = "https://github.com/"
CACHE_DIR_ENV = "POSTHOG_TEMPORAL_SERVER_CACHE_DIR"
ATTEMPTS = 5
# Connect and per-read timeouts, so a silent connection fails within seconds.
REQUEST_TIMEOUT = (5, 10)
# A healthy download takes about a second, while a degraded path trickles kilobytes per second without ever
# tripping the read timeout. An attempt below this rate after the grace period is cut so the retry can land on a
# fast path.
MIN_BYTES_PER_SECOND = 1_000_000
THROUGHPUT_GRACE_SECONDS = 5
DOWNLOAD_DEADLINE_SECONDS = 60
# Longer than ATTEMPTS bounded attempts plus backoff, so a waiting process outlasts the lock holder's retries.
LOCK_TIMEOUT_SECONDS = 300
# xdist gives every worker of one run the same id, so a failure one worker records stops the others in that run
# only, and a later run tries again.
_RUN_ID = os.environ.get("PYTEST_XDIST_TESTRUNUID") or uuid.uuid4().hex


class TemporalServerDownloadError(RuntimeError):
    pass


@frozen
class ServerBinary:
    artifact: str
    file_name: str
    archive_format: str | None


TEST_SERVER = ServerBinary(artifact="temporal-test-server", file_name="temporal-test-server", archive_format=None)
DEV_SERVER = ServerBinary(artifact="cli", file_name="temporal", archive_format="tar.gz")


def cache_dir(platform_params: dict[str, str]) -> Path:
    if configured := os.environ.get(CACHE_DIR_ENV):
        base = Path(configured)
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "posthog" / "temporal-servers"
    # A shared cache directory can serve machines of several platforms, so each gets its own binaries.
    platform_key = f"{platform_params['platform']}-{platform_params['arch']}"
    return base / f"sdk-python-{temporalio.service.__version__}" / platform_key


def _platform_params() -> dict[str, str] | None:
    system = {"linux": "linux", "darwin": "darwin"}.get(sys.platform)
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if system is None or arch is None:
        return None
    return {"platform": system, "arch": arch}


def _download(binary: ServerBinary, platform_params: dict[str, str], dest: Path) -> None:
    # Same query the SDK sends, so the server resolves the same binary version.
    params = {**platform_params, "sdk-name": "sdk-python", "sdk-version": temporalio.service.__version__}
    if binary.archive_format:
        params["format"] = binary.archive_format
    info_response = requests.get(
        f"{DOWNLOAD_BASE_URL}/{binary.artifact}/default", params=params, timeout=REQUEST_TIMEOUT
    )
    info_response.raise_for_status()
    info = info_response.json()
    archive_url: str = info["archiveUrl"]
    file_to_extract: str = info["fileToExtract"]
    if not archive_url.endswith(".tar.gz"):
        raise ValueError(f"unsupported archive format: {archive_url}")
    # temporal.download proxies GitHub release assets under the same path. Its proxy can stall for runners in
    # us-east-1, so the archive comes straight from GitHub. The version lookup above stays on temporal.download.
    if archive_url.startswith(TEMPORAL_ASSETS_URL):
        archive_url = GITHUB_URL + archive_url.removeprefix(TEMPORAL_ASSETS_URL)

    with tempfile.TemporaryDirectory(dir=dest.parent) as work_dir:
        archive_path = Path(work_dir) / "archive.tar.gz"
        started = time.monotonic()
        received = 0
        with requests.get(archive_url, stream=True, timeout=REQUEST_TIMEOUT) as response:
            response.raise_for_status()
            with archive_path.open("wb") as archive_file:
                # chunk_size=None yields data as it arrives, so the checks below run after every read.
                for chunk in response.iter_content(chunk_size=None):
                    archive_file.write(chunk)
                    received += len(chunk)
                    elapsed = time.monotonic() - started
                    if elapsed > DOWNLOAD_DEADLINE_SECONDS:
                        raise TimeoutError(f"download took longer than {DOWNLOAD_DEADLINE_SECONDS}s")
                    if elapsed > THROUGHPUT_GRACE_SECONDS and received / elapsed < MIN_BYTES_PER_SECOND:
                        raise TimeoutError(f"download too slow: {received} bytes in {elapsed:.0f}s")
        # Reading the whole gzip stream checks its CRC, which reading one tar member can stop short of.
        with gzip.open(archive_path) as compressed:
            while compressed.read(1 << 20):
                pass

        extracted_path = Path(work_dir) / binary.file_name
        with tarfile.open(archive_path, "r:gz") as archive:
            member = archive.extractfile(file_to_extract)
            if member is None:
                raise ValueError(f"{file_to_extract} is not a regular file in {archive_url}")
            with member, extracted_path.open("wb") as extracted_file:
                shutil.copyfileobj(member, extracted_file)
        extracted_path.chmod(0o755)
        extracted_path.replace(dest)


def _sdk_cached_binary(binary: ServerBinary) -> Path:
    # Mirrors the file name that sdk-core's ephemeral_server module gives a default-version download.
    return Path(tempfile.gettempdir()) / f"{binary.file_name}-sdk-python-{temporalio.service.__version__}"


# Cached per process, so later tests skip the lock once the binary is in place. A raised error is not
# cached, so the failure marker is what stops each later test from repeating the retries.
@functools.cache
def ensure_binary(binary: ServerBinary) -> Path | None:
    platform_params = _platform_params()
    if platform_params is None:
        return None
    dest = cache_dir(platform_params) / binary.file_name
    if dest.is_file():
        return dest
    if _sdk_cached_binary(binary).is_file():
        # The SDK reuses its own earlier download without network access, so offline runs stay fast.
        return None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        failed_marker = Path(f"{dest}.failed")
        with FileLock(f"{dest}.lock", timeout=LOCK_TIMEOUT_SECONDS):
            if dest.is_file():
                return dest
            failed_in_this_run = failed_marker.is_file() and failed_marker.read_text() == _RUN_ID
            if not failed_in_this_run:
                for attempt in range(1, ATTEMPTS + 1):
                    try:
                        _download(binary, platform_params, dest)
                        failed_marker.unlink(missing_ok=True)
                        return dest
                    except (
                        requests.RequestException,
                        tarfile.TarError,
                        zlib.error,
                        EOFError,
                        OSError,
                        ValueError,
                        KeyError,
                    ) as error:
                        logger.warning("Temporal %s download attempt %d failed: %s", binary.artifact, attempt, error)
                        if attempt < ATTEMPTS:
                            time.sleep(2**attempt)
                failed_marker.write_text(_RUN_ID)
    except Timeout as error:
        # Another process held the lock past every retry it could make, so the network is likely down for this one too.
        raise TemporalServerDownloadError(
            f"Timed out waiting for another process to download the Temporal {binary.artifact} binary"
        ) from error
    except Exception:
        # A broken cache directory or lock is not a network failure, so the SDK can still try its own download.
        logger.warning("Could not cache the Temporal %s binary", binary.artifact, exc_info=True)
        return None
    # The SDK's own download has no read timeout, so a fallback to it after failed retries can hang the job.
    raise TemporalServerDownloadError(
        f"Could not download the Temporal {binary.artifact} binary from {DOWNLOAD_BASE_URL} after {ATTEMPTS} attempts"
    )


def _with_cached_binary(
    start: Callable[..., Awaitable[WorkflowEnvironment]], binary: ServerBinary, prefix: str
) -> Callable[..., Awaitable[WorkflowEnvironment]]:
    @functools.wraps(start)
    async def wrapper(cls: type[WorkflowEnvironment], **kwargs: Any) -> WorkflowEnvironment:
        uses_sdk_default = (
            kwargs.get(f"{prefix}_existing_path") is None
            and kwargs.get(f"{prefix}_download_version", "default") == "default"
            and kwargs.get(f"{prefix}_download_ttl") is None
            and kwargs.get("download_dest_dir") is None
        )
        if uses_sdk_default and (path := await asyncio.to_thread(ensure_binary, binary)) is not None:
            kwargs[f"{prefix}_existing_path"] = str(path)
        return await start(cls, **kwargs)

    return wrapper


_installed = False


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    start_time_skipping = vars(WorkflowEnvironment)["start_time_skipping"].__func__
    start_local = vars(WorkflowEnvironment)["start_local"].__func__
    WorkflowEnvironment.start_time_skipping = classmethod(  # type: ignore[method-assign,assignment]  # ty: ignore[invalid-assignment]
        _with_cached_binary(start_time_skipping, TEST_SERVER, "test_server")
    )
    WorkflowEnvironment.start_local = classmethod(  # type: ignore[method-assign,assignment]  # ty: ignore[invalid-assignment]
        _with_cached_binary(start_local, DEV_SERVER, "dev_server")
    )
    # Downloading now, before any test runs, keeps these requests out of a test's mocked HTTP session.
    for binary in (TEST_SERVER, DEV_SERVER):
        try:
            ensure_binary(binary)
        except TemporalServerDownloadError:
            logger.warning("Could not download the Temporal %s binary before tests", binary.artifact, exc_info=True)
