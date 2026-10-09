"""Throwaway measurement of the jest shard 1 slowdown. Not for merge.

Runs one jest workload twice on one machine: as it runs today, and with one candidate fix.
Both runs share the machine, so the machine's speed cancels out of the comparison.

usage: tmp_jest_leak_probe.py --fix retainmaps --order today-first --shards 2 [-- <jest test selection>]
"""
# ruff: noqa: T201 allow print statements

from __future__ import annotations

import os
import re
import sys
import time
import argparse
import tempfile
import threading
import subprocess
from dataclasses import dataclass
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
NODE_TOOL_CACHE = Path("/opt/hostedtoolcache/node")
PROBE_CONFIG = "jest.probe.config.ts"
DEFAULT_SELECTION = ["--findRelatedTests", "src/lib/constants.tsx"]
SUITE_LINE = re.compile(r"^(PASS|FAIL) (\S+)(?: \((?:[\d.]+ s, )?(\d+) MB heap size\))?")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CRASH = re.compile(r"heap out of memory|FATAL ERROR|SIGKILL|SIGABRT|terminated by another process|ran out of memory")


@dataclass(frozen=True)
class Variant:
    heap_mb: int = 16384
    retain_maps_off: bool = False
    forced_gc: bool = False
    node_major: int | None = None


VARIANTS = {
    "today": Variant(),
    "retainmaps": Variant(retain_maps_off=True),
    "retainmaps-gc": Variant(retain_maps_off=True, forced_gc=True),
    "retainmaps-heap4g": Variant(retain_maps_off=True, heap_mb=4096),
    "node22": Variant(node_major=22),
}


class MemorySampler(threading.Thread):
    """Records the lowest available memory and the most swap in use while jest runs. Linux only."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.lowest_available_mb: int | None = None
        self.most_swap_used_mb = 0
        self._stopped = threading.Event()

    def run(self) -> None:
        meminfo = Path("/proc/meminfo")
        while meminfo.exists() and not self._stopped.wait(10):
            kb = {
                name: int(value.split()[0])
                for name, value in (line.split(":") for line in meminfo.read_text().splitlines())
            }
            available_mb = kb["MemAvailable"] // 1024
            if self.lowest_available_mb is None or available_mb < self.lowest_available_mb:
                self.lowest_available_mb = available_mb
            self.most_swap_used_mb = max(self.most_swap_used_mb, (kb["SwapTotal"] - kb["SwapFree"]) // 1024)

    def stop(self) -> None:
        self._stopped.set()


def node_bin_dir(major: int) -> Path:
    installed = sorted(
        NODE_TOOL_CACHE.glob(f"{major}.*/x64/bin"), key=lambda path: [int(part) for part in path.parts[-3].split(".")]
    )
    if not installed:
        raise SystemExit(f"node {major} is not in {NODE_TOOL_CACHE}")
    return installed[-1]


def run_jest(name: str, variant: Variant, shards: int, selection: list[str], work_dir: Path) -> None:
    env = {
        **os.environ,
        "NODE_OPTIONS": f"--max-old-space-size={variant.heap_mb}",
        "PROBE_FORCED_GC": "1" if variant.forced_gc else "0",
    }
    if variant.node_major is not None:
        env["PATH"] = f"{node_bin_dir(variant.node_major)}{os.pathsep}{env['PATH']}"
    node_version = subprocess.run(["node", "--version"], env=env, capture_output=True, text=True).stdout.strip()

    # pnpm's jest launcher sets NODE_PATH, which jest needs to resolve imports from product folders.
    command = [
        "node_modules/.bin/jest",
        "--forceExit",
        "--passWithNoTests",
        "--logHeapUsage",
        f"--cacheDirectory={work_dir / f'jest-cache-{name}'}",
        f"--shard=1/{shards}",
        *(["--config", PROBE_CONFIG] if variant.retain_maps_off else []),
        *selection,
    ]
    log_path = work_dir / f"jest-{name}.log"
    sampler = MemorySampler()
    sampler.start()
    started = time.monotonic()
    with log_path.open("w") as log:
        status = subprocess.run(command, cwd=FRONTEND, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    wall_seconds = round(time.monotonic() - started)
    sampler.stop()
    report(name, node_version, status, wall_seconds, sampler, log_path)


def report(
    name: str, node_version: str, status: int, wall_seconds: int, sampler: MemorySampler, log_path: Path
) -> None:
    lines = [ANSI.sub("", line) for line in log_path.read_text(errors="replace").splitlines()]
    heaps: list[int] = []
    failed: list[str] = []
    totals = {"Test Suites": "?", "Tests": "?", "Time": "?"}
    for line in lines:
        suite = SUITE_LINE.match(line)
        if suite:
            if suite.group(1) == "FAIL":
                failed.append(suite.group(2))
            if suite.group(3):
                heaps.append(int(suite.group(3)))
        label, _, value = line.partition(":")
        if label in totals:
            totals[label] = value.strip()

    third = max(1, len(heaps) // 3)
    thirds = [median(heaps[:third]), median(heaps[third : 2 * third]), median(heaps[2 * third :])]
    print(f"RESULT variant={name} node={node_version} exit={status} wall_s={wall_seconds} jest_time={totals['Time']}")
    print(f"RESULT   suites: {totals['Test Suites']}; tests: {totals['Tests']}")
    print(f"RESULT   heap MB by third of the run: {thirds[0]} {thirds[1]} {thirds[2]}, max {max(heaps, default=0)}")
    print(f"RESULT   suites reporting over 2000 MB: {sum(heap > 2000 for heap in heaps)} of {len(heaps)}")
    print(
        f"RESULT   memory: lowest available {sampler.lowest_available_mb} MB, most swap used {sampler.most_swap_used_mb} MB"
    )
    for suite_path in sorted(set(failed))[:8]:
        print(f"RESULT   failed suite: {suite_path}")
    for line in [line for line in lines if CRASH.search(line)][:6]:
        print(f"RESULT   crash line: {line.strip()[:200]}")
    if status != 0:
        for line in lines[-25:]:
            print(f"RESULT     {line[:220]}")
    sys.stdout.flush()


def median(values: list[int]) -> int:
    return sorted(values)[len(values) // 2] if values else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", required=True, choices=[name for name in VARIANTS if name != "today"])
    parser.add_argument("--order", required=True, choices=["today-first", "today-second"])
    parser.add_argument("--shards", required=True, type=int)
    parser.add_argument("selection", nargs="*", default=DEFAULT_SELECTION)
    args = parser.parse_args()

    names = ["today", args.fix] if args.order == "today-first" else [args.fix, "today"]
    with tempfile.TemporaryDirectory() as work_dir:
        for name in names:
            run_jest(name, VARIANTS[name], args.shards, args.selection, Path(work_dir))


if __name__ == "__main__":
    main()
