"""Download Temporal's ephemeral test servers into the cache the SDK reads, before tests start them.

`WorkflowEnvironment.start_time_skipping()` and `start_local()` download their server binary on first use,
with no retry and no deadline, so a trickling transfer hangs the test until the job timeout.
The SDK reuses an earlier download that it finds at `<temp dir>/<name>-sdk-python-<sdk version>`, without
network access. CI runs this script before the tests to put both binaries there. curl cuts a stalled
transfer with `--speed-limit` and `--max-time` and starts it again with `--retry`. When this script fails,
the CI step fails, because the SDK would download them again with no deadline.

Usage: python -m posthog.test.temporal_test_servers
"""

from __future__ import annotations

import os
import sys
import json
import tarfile
import platform
import tempfile
import subprocess
from pathlib import Path
from urllib.parse import urlencode

import temporalio.service

from posthog.dataclasses import frozen

DOWNLOAD_BASE_URL = "https://temporal.download"
TEMPORAL_ASSETS_URL = f"{DOWNLOAD_BASE_URL}/assets/"
GITHUB_URL = "https://github.com/"
# The archives are tens of MB, which a healthy runner link moves in under a second. A degraded path trickles a
# few KB/s and never trips a read timeout. curl cuts a transfer that stays below 1 MB/s for 10 s, or that runs
# past 60 s, and retries it, which can land on a fast path.
CURL = (
    "curl",
    "--fail",
    "--silent",
    "--show-error",
    "--location",
    "--retry",
    "3",
    "--retry-all-errors",
    "--connect-timeout",
    "10",
    "--speed-limit",
    "1000000",
    "--speed-time",
    "10",
    "--max-time",
    "60",
)


@frozen
class ServerBinary:
    artifact: str
    cached_name_prefix: str
    archive_format: str | None


# sdk-core names its cached download `<cached_name_prefix>-sdk-python-<sdk version>` (crates/sdk-core/src/
# ephemeral_server/mod.rs in temporalio/sdk-rust). A rename there makes the SDK download the binary again.
BINARIES = (
    ServerBinary(artifact="temporal-test-server", cached_name_prefix="temporal-test-server", archive_format=None),
    ServerBinary(artifact="cli", cached_name_prefix="temporal", archive_format="tar.gz"),
)


def sdk_cache_dir() -> Path:
    # sdk-core uses Rust's `std::env::temp_dir()`, which reads only TMPDIR and falls back to /tmp.
    return Path(os.environ.get("TMPDIR") or "/tmp")


def _curl(url: str, output: Path) -> None:
    # curl truncates an --output file before each retry, but appends to stdout.
    subprocess.run([*CURL, "--output", str(output), url], check=True)


def download(binary: ServerBinary, cache_dir: Path) -> Path:
    sdk_version = temporalio.service.__version__
    dest = cache_dir / f"{binary.cached_name_prefix}-sdk-python-{sdk_version}"
    arch = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64"}[platform.machine().lower()]
    # Same query the SDK sends, so the server resolves the same binary version.
    params = {"arch": arch, "platform": sys.platform, "sdk-name": "sdk-python", "sdk-version": sdk_version}
    if binary.archive_format:
        params["format"] = binary.archive_format

    with tempfile.TemporaryDirectory(dir=cache_dir) as work_dir:
        info_path = Path(work_dir) / "info.json"
        _curl(f"{DOWNLOAD_BASE_URL}/{binary.artifact}/default?{urlencode(params)}", info_path)
        info = json.loads(info_path.read_text())
        archive_url: str = info["archiveUrl"]
        # temporal.download proxies GitHub release assets under the same path. Its proxy can stall for runners in
        # us-east-1, so the archive comes straight from GitHub. The version lookup above stays on temporal.download.
        if archive_url.startswith(TEMPORAL_ASSETS_URL):
            archive_url = GITHUB_URL + archive_url.removeprefix(TEMPORAL_ASSETS_URL)
        archive_path = Path(work_dir) / "archive.tar.gz"
        _curl(archive_url, archive_path)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extract(info["fileToExtract"], work_dir, filter="data")
        extracted = Path(work_dir) / info["fileToExtract"]
        extracted.chmod(0o755)
        extracted.replace(dest)
    return dest


if __name__ == "__main__":
    cache_dir = sdk_cache_dir()
    for binary in BINARIES:
        print(download(binary, cache_dir))  # noqa: T201
