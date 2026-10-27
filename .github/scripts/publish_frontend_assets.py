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

A file whose bytes already match the bucket's copy is skipped, so a republish of an unchanged build
writes nothing new. The comparison is by content, not by name: the image build injects a release id
into content-hashed chunks, so a chunk can keep its name and still change. Sourcemaps never upload.
The build's key list lands at builds/<sha>.json so that a retention job can delete the keys no build
from its window still lists.
"""

import re
import sys
import json
import hashlib
import argparse
import itertools
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

STATIC_PREFIX = "static/"
# The CDN cache rules treat Name-HASH.ext, with an uppercase hash after the last hyphen, as immutable.
# A fixed-name file that matched here would stay cached for a week after it changed.
HASHED_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*-[A-Z0-9]{6,}\.[a-z0-9]+$")
IMMUTABLE_CACHE = "public, max-age=604800, immutable"
REVALIDATE_CACHE = "public, max-age=60, must-revalidate"


class ObjectStore(Protocol):
    def etag(self, key: str) -> str | None: ...

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None: ...


class S3Store:
    def __init__(self, bucket: str, max_connections: int) -> None:
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            config=Config(retries={"mode": "standard", "max_attempts": 5}, max_pool_connections=max_connections),
        )

    def etag(self, key: str) -> str | None:
        try:
            return self.client.head_object(Bucket=self.bucket, Key=key)["ETag"].strip('"')
        except ClientError as error:
            if error.response["Error"]["Code"] in ("404", "NotFound", "NoSuchKey"):
                return None
            raise

    def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type, CacheControl=cache_control
        )


@dataclass(frozen=True)
class PublishReport:
    uploaded: int
    unchanged: int


def scan_build(dist_dir: Path) -> dict[str, Path]:
    """Bucket key to local file for every file in the build, sourcemaps excluded."""
    return {
        STATIC_PREFIX + path.relative_to(dist_dir).as_posix(): path
        for path in sorted(dist_dir.rglob("*"))
        if path.is_file() and path.suffix != ".map"
    }


def content_md5(body: bytes) -> str:
    """What S3 returns as the ETag of a single-part put_object on a bucket without KMS encryption."""
    return hashlib.md5(body, usedforsecurity=False).hexdigest()


def publish(store: ObjectStore, files: dict[str, Path], build_sha: str, workers: int = 32) -> PublishReport:
    hashed = {key: path for key, path in files.items() if HASHED_FILE.match(path.name)}
    fixed = {key: path for key, path in files.items() if key not in hashed}

    def sync(key: str, path: Path, cache_control: str) -> bool:
        body = path.read_bytes()
        if store.etag(key) == content_md5(body):
            return False
        store.put(key, body, mimetypes.guess_type(path.name)[0] or "application/octet-stream", cache_control)
        return True

    def sync_all(batch: dict[str, Path], cache_control: str) -> int:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return sum(pool.map(sync, batch.keys(), batch.values(), itertools.repeat(cache_control)))

    uploaded = sync_all(hashed, IMMUTABLE_CACHE) + sync_all(fixed, REVALIDATE_CACHE)
    store.put(f"builds/{build_sha}.json", json.dumps(sorted(files)).encode(), "application/json", REVALIDATE_CACHE)
    return PublishReport(uploaded, len(files) - uploaded)


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
    print(f"{args.bucket}: uploaded {report.uploaded} files, {report.unchanged} already matched")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
