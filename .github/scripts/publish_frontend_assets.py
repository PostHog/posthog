#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "boto3>=1.40",
# ]
# ///
"""Publish a frontend build to a static-assets bucket.

container-images-cd.yml runs this for each environment before it dispatches the deploy, so a pod
never serves a page that names a file the CDN cannot fetch. Any upload error fails the run.

A content-hashed key already in the bucket is left alone, so a republish creates no new object
versions. Fixed-name files (the posthog-js bundles, the toolbar loader) upload last and always, so
the newest build wins. The build's key list lands at builds/<sha>.json so that a retention job can
delete the keys no build from its window still lists.
"""

import re
import sys
import json
import argparse
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config

STATIC_PREFIX = "static/"
# The CDN cache rules treat Name-HASH.ext, with an uppercase hash after the last hyphen, as immutable.
# A fixed-name file that matched here would stay cached for a week after it changed.
HASHED_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*-[A-Z0-9]{6,}\.[a-z0-9]+$")
IMMUTABLE_CACHE = "public, max-age=604800, immutable"
REVALIDATE_CACHE = "public, max-age=60, must-revalidate"


class ObjectStore(Protocol):
    def keys(self, prefix: str) -> set[str]: ...

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None: ...


class S3Store:
    def __init__(self, bucket: str, max_connections: int) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            config=Config(retries={"mode": "standard", "max_attempts": 5}, max_pool_connections=max_connections),
        )

    def keys(self, prefix: str) -> set[str]:
        found: set[str] = set()
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            found.update(obj["Key"] for obj in page.get("Contents", []))
        return found

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type, CacheControl=cache_control
        )


@dataclass(frozen=True)
class PublishReport:
    uploaded_hashed: int
    skipped_hashed: int
    uploaded_fixed: int


def scan_build(dist_dir: Path) -> dict[str, Path]:
    """Bucket key to local file for every file in the build."""
    return {
        STATIC_PREFIX + path.relative_to(dist_dir).as_posix(): path
        for path in sorted(dist_dir.rglob("*"))
        if path.is_file()
    }


def publish(store: ObjectStore, files: dict[str, Path], build_sha: str, workers: int = 32) -> PublishReport:
    existing = store.keys(STATIC_PREFIX)
    hashed = {key: path for key, path in files.items() if HASHED_FILE.match(path.name)}
    new_hashed = {key: path for key, path in hashed.items() if key not in existing}
    fixed = {key: path for key, path in files.items() if key not in hashed}

    def upload(batch: dict[str, Path], cache_control: str) -> None:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(
                pool.map(
                    lambda item: store.put(
                        item[0],
                        item[1].read_bytes(),
                        mimetypes.guess_type(item[1].name)[0] or "application/octet-stream",
                        cache_control,
                    ),
                    batch.items(),
                )
            )

    upload(new_hashed, IMMUTABLE_CACHE)
    upload(fixed, REVALIDATE_CACHE)
    store.put(f"builds/{build_sha}.json", json.dumps(sorted(files)).encode(), "application/json", REVALIDATE_CACHE)
    return PublishReport(len(new_hashed), len(hashed) - len(new_hashed), len(fixed))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist_dir", type=Path, help="the frontend/dist directory copied out of the image")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--build-sha", required=True)
    parser.add_argument("--workers", type=int, default=32)
    args = parser.parse_args(argv)

    files = scan_build(args.dist_dir)
    if not any(HASHED_FILE.match(path.name) for path in files.values()):
        print(f"::error::{args.dist_dir} has no content-hashed files; is it a production build?")  # noqa: T201
        return 1
    report = publish(S3Store(args.bucket, args.workers), files, args.build_sha, args.workers)
    print(  # noqa: T201
        f"{args.bucket}: uploaded {report.uploaded_hashed} new hashed files, "
        f"kept {report.skipped_hashed} already present, refreshed {report.uploaded_fixed} fixed-name files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
