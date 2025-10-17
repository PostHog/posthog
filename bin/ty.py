#!/usr/bin/env python3
"""Run ty with mypy-baseline integration.

This helper mirrors the workflow provided by mypy-baseline's CLI helpers. It
supports filtering diagnostics during pre-commit runs and updating the
``mypy-baseline.txt`` file from ty's output when new violations are added or
removed.
"""

from __future__ import annotations

import re
import sys
import argparse
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parent.parent
TY_BASELINE_PATH = REPO_ROOT / "ty-baseline.txt"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# ty prints lines like ``path:line[:column]: error[rule] message``.
# Normalizing them makes mypy-baseline treat ty the same way as mypy.
_TY_PATTERN = re.compile(
    r"^(?P<prefix>.+:\d+(?::\d+)?): (?P<severity>error|warn|warning)\[(?P<rule>[^\]]+)\] (?P<message>.*)$"
)


@dataclass(frozen=True)
class TyResult:
    returncode: int
    output: str


def _load_baseline_paths(baseline_path: Path) -> set[str]:
    if not baseline_path.exists():
        return set()
    paths: set[str] = set()
    for raw_line in baseline_path.read_text(encoding="utf-8").splitlines():
        if not raw_line or raw_line.startswith("#"):
            continue
        path, *_rest = raw_line.split(":", 1)
        paths.add(path)
    return paths


def _should_skip(path: str, *, baseline_paths: set[str]) -> bool:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    try:
        relative = candidate.relative_to(REPO_ROOT)
    except ValueError:
        relative = candidate
    return relative.as_posix() in baseline_paths


def _normalize_ty_output(raw_output: str) -> str:
    normalized_lines: list[str] = []
    for raw_line in raw_output.splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("WARN ty is pre-release"):
            continue
        if line.startswith("Checking "):
            continue
        if line.startswith("Found ") and "diagnostic" in line:
            continue
        if line.startswith("info:"):
            continue
        if line.startswith("All checks passed"):
            continue
        match = _TY_PATTERN.match(line)
        if match:
            severity = match.group("severity")
            if severity == "warn":
                severity = "warning"
            normalized_lines.append(
                f"{match.group('prefix')}: {severity}: {match.group('message')}  [{match.group('rule')}]"
            )
            continue
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


def _run_ty(targets: Sequence[str]) -> TyResult:
    if not targets:
        return TyResult(returncode=0, output="")
    proc = subprocess.run(
        ["uv", "run", "ty", "check", "--output-format", "concise", *targets],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return TyResult(returncode=proc.returncode, output=proc.stdout)


def _run_mypy_baseline(
    subcommand: str,
    *,
    input_text: str,
    extra_args: Sequence[str] = (),
) -> TyResult:
    proc = subprocess.run(
        [
            "uv",
            "run",
            "mypy-baseline",
            subcommand,
            "--config",
            str(PYPROJECT_PATH),
            *extra_args,
        ],
        cwd=REPO_ROOT,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return TyResult(returncode=proc.returncode, output=proc.stdout)


def _check(paths: Sequence[str], *, from_hook: bool = False) -> int:
    # Check all files - mypy-baseline filter handles line-level filtering
    filtered_targets = list(paths)
    if not filtered_targets:
        return 0

    ty_result = _run_ty(filtered_targets)
    normalized = _normalize_ty_output(ty_result.output)

    # If ty found no issues, don't even run mypy-baseline filter
    if ty_result.returncode == 0 and not normalized.strip():
        return 0

    baseline_result = _run_mypy_baseline(
        "filter",
        input_text=normalized,
        extra_args=("--hide-stats", "--baseline-path", str(TY_BASELINE_PATH)),
    )
    if baseline_result.output:
        sys.stdout.write(baseline_result.output)
        if not baseline_result.output.endswith("\n"):
            sys.stdout.write("\n")

    # If there are filtered errors (baseline_result has output), that means new errors
    if baseline_result.output:
        sys.stderr.write(
            "\n💡 ty found type errors (fast preflight check). For authoritative results, run mypy locally or check CI.\n"
        )
        return 1

    if ty_result.returncode != 0 and "error[" not in normalized:
        # ty failed for a reason unrelated to diagnostics (e.g. crash).
        sys.stdout.write(ty_result.output)
        if not ty_result.output.endswith("\n"):
            sys.stdout.write("\n")
        return ty_result.returncode

    # All good - no new errors
    return 0


def _sync(paths: Sequence[str]) -> int:
    # Check all Python directories if no paths specified
    targets = list(paths) if paths else ["posthog", "ee", "common", "dags"]
    ty_result = _run_ty(targets)
    normalized = _normalize_ty_output(ty_result.output)

    sync_result = _run_mypy_baseline(
        "sync",
        input_text=normalized,
        extra_args=("--hide-stats", "--baseline-path", str(TY_BASELINE_PATH)),
    )

    if sync_result.output:
        sys.stdout.write(sync_result.output)
        if not sync_result.output.endswith("\n"):
            sys.stdout.write("\n")

    if sync_result.returncode != 0:
        return sync_result.returncode

    if ty_result.returncode != 0 and "error[" not in normalized:
        # Preserve failures unrelated to diagnostics so they aren't hidden.
        sys.stdout.write(ty_result.output)
        if not ty_result.output.endswith("\n"):
            sys.stdout.write("\n")
        return ty_result.returncode

    return 0


def _parse_args(argv: Sequence[str]) -> tuple[str, list[str], bool]:
    parser = argparse.ArgumentParser(
        description="Run ty with mypy-baseline integration.",
    )
    subparsers = parser.add_subparsers(dest="command")

    check_parser = subparsers.add_parser(
        "check",
        help="Run ty on the given paths, filtering diagnostics using mypy-baseline.",
    )
    check_parser.add_argument("paths", nargs="*")

    sync_parser = subparsers.add_parser(
        "sync",
        help="Update mypy-baseline.txt by re-running ty on the provided paths.",
    )
    sync_parser.add_argument("paths", nargs="*")

    # ``bin/ty.py <files>`` should behave like ``bin/ty.py check <files>`` for lint-staged.
    # When called this way (no subcommand), it's from a hook
    from_hook: bool = bool(argv and not argv[0].startswith("-") and argv[0] not in {"check", "sync"})
    if from_hook:
        argv = ["check", *argv]

    args = parser.parse_args(argv)
    command: str = cast(str, args.command or "check")
    paths: list[str] = cast(list[str], getattr(args, "paths", []) or [])
    return command, paths, from_hook


def main(argv: Sequence[str] | None = None) -> int:
    command, paths, from_hook = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    if command == "check":
        return _check(paths, from_hook=from_hook)
    if command == "sync":
        return _sync(paths)
    raise AssertionError(f"Unknown command: {command}")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
