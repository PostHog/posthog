#!/usr/bin/env python3
"""Download and validate inert telemetry inputs from one Depot Backend CI run."""

from __future__ import annotations

import os
import re
import json
import stat
import zipfile
import argparse
import tempfile
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

JUNIT_NAME = re.compile(r"^(?:junit-results-backend|product-junit-results)-[A-Za-z0-9._-]+$")
SELECTION_NAME = re.compile(r"^depot-test-selection-input-pr(?P<pr>[0-9]+)-attempt(?P<attempt>[0-9]+)$")
MAX_ARTIFACTS = 200
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_SELECTION_BYTES = 64 * 1024


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    name: str
    size_bytes: int
    attempt: int
    created_at: datetime


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"artifact {field} must be a non-empty string")
    return value


def _required_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"artifact {field} must be a non-negative integer")
    return value


def _required_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"artifact {field} must be a timestamp")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"artifact {field} must be a timestamp") from error
    if timestamp.tzinfo is None:
        raise ValueError(f"artifact {field} must include a timezone")
    return timestamp


def parse_artifacts(payload: object, run_id: str, workflow_id: str) -> list[Artifact]:
    if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
        raise ValueError("Depot artifact response has no artifacts list")
    parsed: list[Artifact] = []
    for raw in payload["artifacts"]:
        if not isinstance(raw, dict):
            raise ValueError("Depot artifact entry must be an object")
        if raw.get("run_id") != run_id or raw.get("workflow_id") != workflow_id:
            raise ValueError("Depot returned an artifact outside the requested run")
        if raw.get("workflow_path") != "ci-backend.yml":
            continue
        name = _required_string(raw.get("name"), "name")
        if not (JUNIT_NAME.fullmatch(name) or SELECTION_NAME.fullmatch(name)):
            continue
        parsed.append(
            Artifact(
                artifact_id=_required_string(raw.get("artifact_id"), "id"),
                name=name,
                size_bytes=_required_int(raw.get("size_bytes"), "size"),
                attempt=_required_int(raw.get("attempt"), "attempt"),
                created_at=_required_timestamp(raw.get("created_at"), "created_at"),
            )
        )
    if len(parsed) > MAX_ARTIFACTS:
        raise ValueError(f"refusing to process {len(parsed)} artifacts")
    if any(artifact.size_bytes > MAX_ARTIFACT_BYTES for artifact in parsed):
        raise ValueError("an artifact exceeds the per-artifact size limit")
    if sum(artifact.size_bytes for artifact in parsed) > MAX_TOTAL_BYTES:
        raise ValueError("artifacts exceed the total size limit")
    return parsed


def select_attempt(
    artifacts: list[Artifact],
    *,
    run_attempt: int | None,
    attempt_started_at: str | None,
    attempt_finished_at: str | None,
) -> tuple[int | None, list[Artifact]]:
    if run_attempt is not None:
        return run_attempt, [artifact for artifact in artifacts if artifact.attempt == run_attempt]
    if attempt_started_at is None or attempt_finished_at is None:
        raise ValueError("retry telemetry requires both attempt timestamps")
    started = _required_timestamp(attempt_started_at, "attempt start")
    finished = _required_timestamp(attempt_finished_at, "attempt finish")
    if finished < started:
        raise ValueError("retry telemetry has an invalid attempt window")
    candidates = [
        artifact
        for artifact in artifacts
        if JUNIT_NAME.fullmatch(artifact.name) and artifact.attempt > 1 and started <= artifact.created_at <= finished
    ]
    if not candidates:
        return None, []
    selected_attempt = max(artifact.attempt for artifact in candidates)
    return selected_attempt, [artifact for artifact in candidates if artifact.attempt == selected_attempt]


def safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if sum(member.file_size for member in members) > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact expands beyond the size limit")
        for member in members:
            parts = PurePosixPath(member.filename).parts
            if not parts or member.filename.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe artifact member: {member.filename!r}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"artifact symlink is not allowed: {member.filename!r}")
            target = destination.joinpath(*parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.file_size > MAX_ARTIFACT_BYTES:
                raise ValueError(f"artifact member is too large: {member.filename!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, target.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)


def _download(artifact: Artifact, org: str, destination: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temporary:
        archive = Path(temporary.name)
    try:
        subprocess.run(
            [
                "depot",
                "ci",
                "artifacts",
                "download",
                artifact.artifact_id,
                "--org",
                org,
                "--output-file",
                str(archive),
            ],
            check=True,
        )
        safe_extract(archive, destination)
    finally:
        archive.unlink(missing_ok=True)


def validated_selection(
    payload: object, *, pr_number: int, head_sha: str, head_ref: str, run_id: str
) -> dict[str, str | int | bool | None]:
    if not isinstance(payload, dict):
        raise ValueError("selection telemetry must be an object")
    allowed = {
        "suite",
        "mode",
        "run_poe",
        "run_temporal",
        "changed_file_count",
        "selected_test_count",
        "full_run_reasons_count",
        "selected_test_seconds",
        "skipped_test_seconds",
        "run_legacy",
        "run_legacy_reason",
        "product_matrix_narrowed",
        "product_count",
        "product_count_full",
    }
    properties: dict[str, str | int | bool | None] = {}
    for key in allowed:
        value = payload.get(key)
        if value is not None and not isinstance(value, (str, int, bool)):
            raise ValueError(f"selection property {key!r} has an invalid type")
        properties[key] = value
    if properties["suite"] != "backend":
        raise ValueError("selection telemetry is not for the backend suite")
    if properties["mode"] not in {"selected", "full", "skip"}:
        raise ValueError("selection telemetry has an invalid mode")
    properties.update(
        {
            "ci_engine": "depot",
            "event_type": "pull_request",
            "branch": head_ref,
            "sha": head_sha,
            "pr_number": pr_number,
            "run_id": run_id,
        }
    )
    return properties


def append_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise RuntimeError("GITHUB_OUTPUT is not set")
    with Path(output_path).open("a") as output:
        output.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--org", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--attempt-started-at")
    parser.add_argument("--attempt-finished-at")
    parser.add_argument("--junit-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.run_attempt is not None and args.run_attempt < 1:
        parser.error("--run-attempt must be positive")
    if args.run_attempt is not None and (args.attempt_started_at or args.attempt_finished_at):
        parser.error("--run-attempt cannot be combined with an attempt window")
    if args.run_attempt is None and not (args.attempt_started_at and args.attempt_finished_at):
        parser.error("provide --run-attempt or both attempt window timestamps")

    listed = subprocess.run(
        [
            "depot",
            "ci",
            "artifacts",
            "list",
            args.run_id,
            "--workflow",
            args.workflow_id,
            "--org",
            args.org,
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    artifacts = parse_artifacts(json.loads(listed.stdout), args.run_id, args.workflow_id)
    run_attempt, attempt_artifacts = select_attempt(
        artifacts,
        run_attempt=args.run_attempt,
        attempt_started_at=args.attempt_started_at,
        attempt_finished_at=args.attempt_finished_at,
    )
    if run_attempt is None:
        append_output("run_attempt", "0")
        append_output("has_junit", "false")
        append_output("has_selection", "false")
        return 0
    junit = [artifact for artifact in attempt_artifacts if JUNIT_NAME.fullmatch(artifact.name)]
    selection = [
        artifact
        for artifact in attempt_artifacts
        if (match := SELECTION_NAME.fullmatch(artifact.name)) and int(match.group("pr")) == args.pr_number
    ]
    args.junit_dir.mkdir(parents=True, exist_ok=True)
    for artifact in junit:
        _download(artifact, args.org, args.junit_dir / artifact.name)

    append_output("run_attempt", str(run_attempt))
    append_output("has_junit", str(bool(junit)).lower())
    if selection:
        chosen = max(selection, key=lambda artifact: artifact.artifact_id)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _download(chosen, args.org, directory)
            path = directory / "selection.json"
            if not path.is_file() or path.stat().st_size > MAX_SELECTION_BYTES:
                raise ValueError("selection artifact is missing or too large")
            properties = validated_selection(
                json.loads(path.read_text()),
                pr_number=args.pr_number,
                head_sha=args.head_sha,
                head_ref=args.head_ref,
                run_id=args.run_id,
            )
        append_output("selection", json.dumps(properties, separators=(",", ":"), sort_keys=True))
        append_output("has_selection", "true")
    else:
        append_output("has_selection", "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
