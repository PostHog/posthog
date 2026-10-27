#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "boto3>=1.40",
# ]
# ///
"""Publish a frontend build to a static-assets bucket and verify that every file landed.

container-images-cd.yml runs this for each environment before it dispatches the deploy, so a pod
never serves a page that names a file the CDN cannot fetch.

A content-hashed key already in the bucket is left alone, so a republish creates no new object
versions. Fixed-name files (the posthog-js bundles, the toolbar loader) upload last and always, so
the newest build wins. The build's key list lands at builds/<sha>.json for retention tooling.
"""

import re
import sys
import json
import argparse
import mimetypes
from collections.abc import Iterable
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
class Build:
    hashed: dict[str, Path]
    fixed: dict[str, Path]

    @property
    def keys(self) -> set[str]:
        return self.hashed.keys() | self.fixed.keys()


@dataclass(frozen=True)
class PublishReport:
    uploaded_hashed: int
    skipped_hashed: int
    uploaded_fixed: int


class MissingAfterUpload(Exception):
    def __init__(self, keys: Iterable[str]) -> None:
        self.keys = sorted(keys)
        super().__init__(f"{len(self.keys)} files are not in the bucket after upload: {', '.join(self.keys[:20])}")


def scan_build(dist_dir: Path) -> Build:
    hashed: dict[str, Path] = {}
    fixed: dict[str, Path] = {}
    for file in sorted(path for path in dist_dir.rglob("*") if path.is_file()):
        key = STATIC_PREFIX + file.relative_to(dist_dir).as_posix()
        (hashed if HASHED_FILE.match(file.name) else fixed)[key] = file
    return Build(hashed, fixed)


def content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def publish(store: ObjectStore, build: Build, build_sha: str, workers: int = 32) -> PublishReport:
    existing = store.keys(STATIC_PREFIX)
    new_hashed = {key: path for key, path in build.hashed.items() if key not in existing}

    def upload(files: dict[str, Path], cache_control: str) -> None:
        def one(item: tuple[str, Path]) -> None:
            key, path = item
            store.put(key, path.read_bytes(), content_type(path), cache_control)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, files.items()))

    upload(new_hashed, IMMUTABLE_CACHE)
    upload(build.fixed, REVALIDATE_CACHE)
    store.put(f"builds/{build_sha}.json", json.dumps(sorted(build.keys)).encode(), "application/json", REVALIDATE_CACHE)

    missing = build.keys - store.keys(STATIC_PREFIX)
    if missing:
        raise MissingAfterUpload(missing)
    return PublishReport(len(new_hashed), len(build.hashed) - len(new_hashed), len(build.fixed))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist_dir", type=Path, help="the frontend/dist directory copied out of the image")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--build-sha", required=True)
    parser.add_argument("--workers", type=int, default=32)
    args = parser.parse_args(argv)

    build = scan_build(args.dist_dir)
    if not build.hashed:
        print(f"::error::{args.dist_dir} has no content-hashed files; is it a production build?")  # noqa: T201
        return 1
    try:
        report = publish(S3Store(args.bucket, args.workers), build, args.build_sha, args.workers)
    except MissingAfterUpload as error:
        print(f"::error::{error}")  # noqa: T201
        return 1
    print(  # noqa: T201
        f"{args.bucket}: uploaded {report.uploaded_hashed} new hashed files, "
        f"kept {report.skipped_hashed} already present, refreshed {report.uploaded_fixed} fixed-name files"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
