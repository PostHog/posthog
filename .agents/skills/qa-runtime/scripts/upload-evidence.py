#!/usr/bin/env python3
"""Upload qa-runtime evidence files to the posthog.com Strapi CMS.

Reads credentials from POSTHOG_COM_EMAIL and POSTHOG_COM_PASSWORD. Caches the
issued JWT at ~/.cache/posthog-cdn-jwt with mode 0600 and re-mints once on a
401. Renames each file to the qa-runtime convention before upload and writes a
JSON manifest mapping local paths to public URLs.

If credentials are missing, exits with code 2 and prints a non-blocking warning
so the calling skill can degrade to local-path evidence in the PR comment.
"""

from __future__ import annotations

import os
import re
import sys
import json
import uuid
import argparse
import mimetypes
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

STRAPI_BASE_URL = "https://better-animal-d658c56969.strapiapp.com"
JWT_CACHE_PATH = Path.home() / ".cache" / "posthog-cdn-jwt"
EXIT_NO_CREDENTIALS = 2
EXIT_FATAL = 3
MAX_DESCRIPTION_LEN = 60


@dataclass
class UploadResult:
    local: str
    remote_name: str
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


def load_cached_jwt() -> str | None:
    if not JWT_CACHE_PATH.exists():
        return None
    try:
        token = JWT_CACHE_PATH.read_text().strip()
        return token or None
    except OSError:
        return None


def store_jwt(token: str) -> None:
    JWT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    JWT_CACHE_PATH.write_text(token)
    try:
        os.chmod(JWT_CACHE_PATH, 0o600)
    except OSError:
        pass


def mint_jwt(email: str, password: str) -> str:
    body = json.dumps({"identifier": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{STRAPI_BASE_URL}/api/auth/local",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"auth failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"auth failed: {exc.reason}") from exc
    token = payload.get("jwt")
    if not token:
        raise RuntimeError("auth response missing jwt")
    store_jwt(token)
    return token


def build_multipart(file_path: Path, remote_name: str) -> tuple[bytes, str]:
    boundary = f"----qa-runtime-{uuid.uuid4().hex}"
    mime_type = mimetypes.guess_type(remote_name)[0] or "application/octet-stream"
    body_parts: list[bytes] = []
    body_parts.append(f"--{boundary}\r\n".encode())
    body_parts.append(
        (
            f'Content-Disposition: form-data; name="files"; filename="{remote_name}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode()
    )
    body_parts.append(file_path.read_bytes())
    body_parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(body_parts), boundary


def upload_one(file_path: Path, remote_name: str, jwt: str) -> tuple[int, str]:
    # Returns (http_status, body). For non-HTTP failures (DNS, connection
    # refused, socket timeout) returns (0, "<error description>") so the
    # caller records a failed manifest entry instead of crashing the run.
    body, boundary = build_multipart(file_path, remote_name)
    req = urllib.request.Request(
        f"{STRAPI_BASE_URL}/api/upload",
        data=body,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as exc:
        return 0, f"network error: {exc.reason}"
    except (TimeoutError, OSError) as exc:
        return 0, f"network error: {exc}"


def extract_url(response_body: str) -> str:
    payload = json.loads(response_body)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("upload response not a non-empty array")
    url = payload[0].get("url")
    if not url:
        raise RuntimeError("upload response missing url")
    if url.startswith("/"):
        url = STRAPI_BASE_URL.rstrip("/") + url
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


def remote_filename(repo: str, pr: int, sha: str, index: int, description: str, suffix: str) -> str:
    return f"qa-{kebab(repo)}-pr{pr}-{sha}-{index:03d}-{kebab(description)}{suffix}"


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

    email = os.environ.get("POSTHOG_COM_EMAIL")
    password = os.environ.get("POSTHOG_COM_PASSWORD")
    if not email or not password:
        manifest = Manifest(skipped_no_env=True)
        sys.stderr.write(
            "qa-runtime upload: POSTHOG_COM_EMAIL/POSTHOG_COM_PASSWORD not set; "
            "skipping upload. PR comment will use local paths.\n"
        )
        if args.output:
            args.output.write_text(manifest.to_json())
        sys.stdout.write(manifest.to_json() + "\n")
        return EXIT_NO_CREDENTIALS

    try:
        repo = repo_slug_from_origin()
        sha = git_short_sha()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        sys.stderr.write(f"qa-runtime upload: git inspection failed: {exc}\n")
        return EXIT_FATAL

    jwt = load_cached_jwt()
    manifest = Manifest()

    for index, (local_path, description) in enumerate(args.files, start=1):
        remote_name = remote_filename(repo, args.pr, sha, index, description, local_path.suffix)
        result = UploadResult(local=str(local_path), remote_name=remote_name)

        for attempt in (1, 2):
            if not jwt:
                try:
                    jwt = mint_jwt(email, password)
                except RuntimeError as exc:
                    result.error = str(exc)
                    break
            status, body = upload_one(local_path, remote_name, jwt)
            if status == 200 or status == 201:
                try:
                    result.url = extract_url(body)
                except (RuntimeError, json.JSONDecodeError) as exc:
                    result.error = f"parse upload response: {exc}"
                break
            if status == 401 and attempt == 1:
                jwt = None  # force re-mint and retry once
                continue
            if status == 0:
                # Network failure already described in body (no token/HTML risk).
                result.error = body
                break
            # Don't echo response body verbatim - it can be HTML or include hints.
            result.error = f"HTTP {status}"
            break

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
