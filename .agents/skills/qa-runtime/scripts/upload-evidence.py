#!/usr/bin/env python3
"""Upload qa-runtime evidence files directly to Cloudinary.

Reads credentials from `CLOUDINARY_URL` in the form
`cloudinary://<api_key>:<api_secret>@<cloud_name>`. Renames each file to the
qa-runtime convention, signs a Cloudinary `/image/upload` POST, and writes a
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
import uuid
import hashlib
import argparse
import mimetypes
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

EXIT_NO_CREDENTIALS = 2
EXIT_FATAL = 3
MAX_DESCRIPTION_LEN = 60

# Repo root is four parents up: scripts -> qa-runtime -> skills -> .agents -> repo.
REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_repo_dotenv() -> None:
    """Load `<repo>/.env` so the script works from a non-interactive shell.

    Mirrors the pattern in `products/query_performance_ai/orchestrator/coordinator.py`:
    lazy `python-dotenv` import so the script still runs in environments where
    the package is unavailable. `override=False` means anything already in
    `os.environ` wins.
    """
    env_path = REPO_ROOT / ".env"
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
    return m.group(3), m.group(1), m.group(2)


def cloudinary_signature(params: dict[str, str], api_secret: str) -> str:
    # SHA1 of alphabetized "k=v" pairs joined by "&", plus api_secret appended.
    # Standard Cloudinary signing rule for upload params.
    payload = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1((payload + api_secret).encode("utf-8")).hexdigest()


def build_multipart(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = f"----qa-runtime-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        parts.append(str(v).encode("utf-8"))
        parts.append(b"\r\n")
    mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode()
    )
    parts.append(file_path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


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
    body, boundary = build_multipart(fields, file_path)
    req = urllib.request.Request(
        f"https://api.cloudinary.com/v1_1/{cloud_name}/image/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Don't echo response body - may contain hints. Caller logs HTTP <code>.
        return exc.code, ""
    except urllib.error.URLError as exc:
        return 0, f"network error: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return 0, f"network error: {exc}"


def extract_url(response_body: str) -> str:
    payload = json.loads(response_body)
    url = payload.get("secure_url")
    if not url:
        raise RuntimeError("upload response missing secure_url")
    return url


def parse_file_arg(raw: str) -> tuple[Path, str]:
    # Format: <local_path>:<kebab-description>. Path may contain colons on Windows,
    # but qa-runtime runs on POSIX, so split on the last colon.
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
            "qa-runtime upload: CLOUDINARY_URL not set; skipping upload. PR comment will use local paths.\n"
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
        sys.stderr.write(f"qa-runtime upload: setup failed: {exc}\n")
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
