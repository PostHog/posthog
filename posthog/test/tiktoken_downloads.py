"""Bound the download tiktoken makes the first time a process loads an encoding.

tiktoken fetches encoding files with `requests.get` and no timeout. It caches them in
`$TMPDIR/data-gym-cache` unless `TIKTOKEN_CACHE_DIR` is set, and every CI job starts with an
empty temp directory, so the first test that counts tokens downloads them. A stalled connection
then hangs that test until the job timeout. This module replaces tiktoken's fetch with one that
has timeouts, a deadline and retries, so the test fails instead. tiktoken still owns the cache
and the hash check.
"""

from __future__ import annotations

import time
import logging
from collections.abc import Callable

import requests
import tiktoken.load

from posthog.test.download_deadline import call_with_deadline

logger = logging.getLogger(__name__)

ATTEMPTS = 3
# Connect and per-read timeouts, so a silent connection fails within seconds.
REQUEST_TIMEOUT = (5, 10)
# The largest encoding file is a few megabytes, so an attempt past this deadline is on a degraded path.
DOWNLOAD_DEADLINE_SECONDS = 60


def _download(url: str) -> bytes:
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def _download_with_retries(url: str) -> bytes:
    for attempt in range(1, ATTEMPTS):
        try:
            return call_with_deadline(lambda: _download(url), DOWNLOAD_DEADLINE_SECONDS)
        except (requests.RequestException, TimeoutError) as error:
            logger.warning("tiktoken download attempt %d of %s failed: %s", attempt, url, error)
            time.sleep(2**attempt)
    return call_with_deadline(lambda: _download(url), DOWNLOAD_DEADLINE_SECONDS)


def install() -> None:
    # vars() raises KeyError if tiktoken renames the function, instead of adding an attribute nothing calls.
    read_file: Callable[[str], bytes] = vars(tiktoken.load)["read_file"]

    def bounded_read_file(blobpath: str) -> bytes:
        if blobpath.startswith(("http://", "https://")):
            return _download_with_retries(blobpath)
        return read_file(blobpath)

    tiktoken.load.read_file = bounded_read_file  # ty: ignore[invalid-assignment]
