#!/usr/bin/env python3
"""Upload qa-frontend evidence files directly to Cloudinary.

Reads credentials from `CLOUDINARY_URL` in the form
`cloudinary://<api_key>:<api_secret>@<cloud_name>`. Renames each file to the
qa-frontend convention, signs a Cloudinary `/image/upload` POST, and writes a
JSON manifest mapping local paths to the returned `secure_url`.

If `CLOUDINARY_URL` is missing, exits with code 2 and prints a non-blocking
warning so the calling skill can degrade to local-path evidence in the PR
comment.
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import hashlib
import argparse
import mimetypes
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import requests

EXIT_NO_CREDENTIALS = 2
EXIT_FATAL = 3
MAX_DESCRIPTION_LEN = 60


def _repo_root() -> Path | None:
    # Ask git for the repo root rather than hardcoding `parents[N]`. Makes the
    # script work regardless of how/where the skill is installed (`.agents/skills/`,
    # `skills/`, or anywhere else under a git checkout).
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(output) if output else None


def _load_repo_dotenv() -> None:
    """Load `<repo>/.env` so the script works from a non-interactive shell.

    Mirrors the pattern in `products/query_performance_ai/orchestrator/coordinator.py`:
    lazy `python-dotenv` import so the script still runs in environments where
    the package is unavailable. `override=False` means anything already in
    `os.environ` wins.
    """
    repo_root = _repo_root()
    if repo_root is None:
        return
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv  # noqa: PLC0415 - keeps the dep on the optional path
    except ImportError:
        return
    load_dotenv(env_path, override=False)


@dataclass
class UploadResult:
    local: str
    public_id: str
    url: str | None = None
    error: str | None = None


@dataclass
class Manifest:
    uploaded: list[UploadResult] = field(default_factory=list)
    failed: list[UploadResult] = field(default_factory=list)
    skipped_no_env: bool = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "skipped_no_env": self.skipped_no_env,
                "uploaded": [r.__dict__ for r in self.uploaded],
                "failed": [r.__dict__ for r in self.failed],
            },
            indent=2,
        )


def kebab(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:MAX_DESCRIPTION_LEN] or "evidence"


def git_short_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "--short=7", "HEAD"], text=True).strip()


def repo_slug_from_origin() -> str:
    url = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
    # Accept https://github.com/owner/repo(.git) and git@github.com:owner/repo(.git)
    match = re.search(r"[/:]([^/:]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise RuntimeError(f"could not parse repo from origin URL: {url}")
    return match.group(2)


def parse_cloudinary_url(url: str) -> tuple[str, str, str]:
    # Returns (cloud_name, api_key, api_secret).
    m = re.match(r"^cloudinary://([^:]+):([^@]+)@(.+)$", url)
    if not m:
        raise RuntimeError("CLOUDINARY_URL must be cloudinary://<key>:<secret>@<cloud>")
    cloud_name = m.group(3)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", cloud_name):
        raise RuntimeError("CLOUDINARY_URL cloud name may contain only letters, numbers, underscores, and hyphens")
    return cloud_name, m.group(1), m.group(2)


def cloudinary_signature(params: dict[str, str], api_secret: str) -> str:
    # SHA-256 of alphabetized "k=v" pairs joined by "&", plus api_secret appended.
    # Cloudinary supports SHA-256 signatures for upload params.
    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha256((payload + api_secret).encode("utf-8")).hexdigest()


def upload_one(cloud_name: str, api_key: str, api_secret: str, file_path: Path, public_id: str) -> tuple[int, str]:
    # Returns (http_status, body). For non-HTTP failures (DNS, connection
    # refused, socket timeout) returns (0, "<error description>") so the
    # caller records a failed manifest entry instead of crashing the run.
    timestamp = str(int(time.time()))
    sign_params = {"public_id": public_id, "timestamp": timestamp}
    signature = cloudinary_signature(sign_params, api_secret)
    fields = {
        "api_key": api_key,
        "timestamp": timestamp,
        "public_id": public_id,
        "signature": signature,
    }
    upload_url = f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    try:
        with file_path.open("rb") as file_handle:
            response = requests.post(
                upload_url,
                data=fields,
                files={"file": (file_path.name, file_handle, mime_type)},
                timeout=120,
            )
    except requests.RequestException as exc:
        return 0, f"network error: {exc}"
    if response.ok:
        return response.status_code, response.text
    # Don't echo response body - may contain hints. Caller logs HTTP <code>.
    return response.status_code, ""


def extract_url(response_body: str) -> str:
    payload = json.loads(response_body)
    url = payload.get("secure_url")
    if not url:
        raise RuntimeError("upload response missing secure_url")
    return url


def parse_file_arg(raw: str) -> tuple[Path, str]:
    # Format: <local_path>:<kebab-description>. Path may contain colons on Windows,
    # but qa-frontend runs on POSIX, so split on the last colon.
    if ":" not in raw:
        raise argparse.ArgumentTypeError(f"--file expects '<path>:<description>', got: {raw}")
    path_str, description = raw.rsplit(":", 1)
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"file not found: {path}")
    if not description.strip():
        raise argparse.ArgumentTypeError(f"empty description in: {raw}")
    return path, description


def public_id_for(repo: str, pr: int, sha: str, index: int, description: str) -> str:
    return f"qa-{kebab(repo)}-pr{pr}-{sha}-{index:03d}-{kebab(description)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True, help="PR number")
    parser.add_argument(
        "--file",
        dest="files",
        action="append",
        required=True,
        type=parse_file_arg,
        help="Repeated: <local_path>:<kebab-description>",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write manifest JSON to this path (also prints to stdout)",
    )
    args = parser.parse_args()

    _load_repo_dotenv()
    cloudinary_url = os.environ.get("CLOUDINARY_URL")
    if not cloudinary_url:
        manifest = Manifest(skipped_no_env=True)
        sys.stderr.write(
            "qa-frontend upload: CLOUDINARY_URL not set; skipping upload. PR comment will use local paths.\n"
        )
        if args.output:
            args.output.write_text(manifest.to_json())
        sys.stdout.write(manifest.to_json() + "\n")
        return EXIT_NO_CREDENTIALS

    try:
        cloud_name, api_key, api_secret = parse_cloudinary_url(cloudinary_url)
        repo = repo_slug_from_origin()
        sha = git_short_sha()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        sys.stderr.write(f"qa-frontend upload: setup failed: {exc}\n")
        return EXIT_FATAL

    manifest = Manifest()

    for index, (local_path, description) in enumerate(args.files, start=1):
        pid = public_id_for(repo, args.pr, sha, index, description)
        result = UploadResult(local=str(local_path), public_id=pid)

        status, body = upload_one(cloud_name, api_key, api_secret, local_path, pid)
        if status in (200, 201):
            try:
                result.url = extract_url(body)
            except (RuntimeError, json.JSONDecodeError) as exc:
                result.error = f"parse upload response: {exc}"
        elif status == 0:
            result.error = body  # already a redacted network-error string
        else:
            result.error = f"HTTP {status}"

        if result.url:
            manifest.uploaded.append(result)
        else:
            manifest.failed.append(result)

    serialized = manifest.to_json()
    if args.output:
        args.output.write_text(serialized)
    sys.stdout.write(serialized + "\n")
    return 0 if not manifest.failed else 1


if __name__ == "__main__":
    sys.exit(main())
