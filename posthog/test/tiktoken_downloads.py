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
import threading
from collections.abc import Callable

import requests
import tiktoken.load

logger = logging.getLogger(__name__)

ATTEMPTS = 3
# Connect and per-read timeouts, so a silent connection fails within seconds.
REQUEST_TIMEOUT = (5, 10)
# The largest encoding file is a few megabytes, so an attempt past this deadline is on a degraded path.
DOWNLOAD_DEADLINE_SECONDS = 60


def _download(url: str) -> bytes:
    outcome: list[bytes | Exception] = []

    def fetch() -> None:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            outcome.append(response.content)
        except Exception as error:
            outcome.append(error)

    # A trickle that sends a few bytes before each read timeout keeps every read alive, and a streamed read
    # blocks until its whole chunk arrives, so only a wall-clock deadline bounds the download. The thread is a
    # daemon because the interpreter would otherwise wait for an abandoned download at exit.
    thread = threading.Thread(target=fetch, daemon=True)
    thread.start()
    thread.join(DOWNLOAD_DEADLINE_SECONDS)
    if not outcome:
        raise TimeoutError(f"download of {url} took longer than {DOWNLOAD_DEADLINE_SECONDS}s")
    if isinstance(outcome[0], Exception):
        raise outcome[0]
    return outcome[0]


def _download_with_retries(url: str) -> bytes:
    for attempt in range(1, ATTEMPTS):
        try:
            return _download(url)
        except (requests.RequestException, TimeoutError) as error:
            logger.warning("tiktoken download attempt %d of %s failed: %s", attempt, url, error)
            time.sleep(2**attempt)
    return _download(url)


def install() -> None:
    # vars() raises KeyError if tiktoken renames the function, instead of adding an attribute nothing calls.
    read_file: Callable[[str], bytes] = vars(tiktoken.load)["read_file"]

    def bounded_read_file(blobpath: str) -> bytes:
        if blobpath.startswith(("http://", "https://")):
            return _download_with_retries(blobpath)
        return read_file(blobpath)

    tiktoken.load.read_file = bounded_read_file  # ty: ignore[invalid-assignment]
