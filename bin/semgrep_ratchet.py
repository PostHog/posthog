#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Hold the findings of one semgrep rule to a checked-in, per-file baseline.

The baseline lists each file that still has findings, with its finding count. The check fails
when a file has more findings than its baseline count (new debt), and also when it has fewer
(the baseline is stale). So the baseline only goes down, and each migration lowers it.

A file that semgrep reports an error for (a timeout, a parse error) can have missing findings, so
the check does not call its line stale, and `--update` does not lower its line.

    semgrep --config <rule>.yaml --json --output findings.json <paths>
    bin/semgrep_ratchet.py --findings findings.json --baseline <baseline>.txt
    bin/semgrep_ratchet.py --findings findings.json --baseline <baseline>.txt --update
"""

import sys
import json
import argparse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RatchetResult:
    over: dict[str, tuple[int, int]] = field(default_factory=dict)
    stale: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Fewer findings than the baseline in a file with a semgrep error. Not a failure.
    unchecked: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.over and not self.stale


def count_findings(semgrep_output: dict) -> Counter[str]:
    return Counter(result["path"] for result in semgrep_output.get("results", []))


def error_paths(semgrep_output: dict) -> frozenset[str]:
    paths: set[str] = set()
    for error in semgrep_output.get("errors", []):
        if error.get("path"):
            paths.add(error["path"])
        paths.update(span["file"] for span in error.get("spans") or [] if span.get("file"))
    return frozenset(paths)


def parse_baseline(text: str) -> dict[str, int]:
    baseline: dict[str, int] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        path, _, count = line.rpartition(" ")
        if not path or not count.isdigit() or int(count) < 1:
            raise ValueError(f"Baseline line {line_number} is not '<path> <count>': {raw_line!r}")
        if path in baseline:
            raise ValueError(f"Baseline line {line_number} repeats {path}")
        baseline[path] = int(count)
    return baseline


def compare(
    findings: Counter[str], baseline: dict[str, int], incomplete: frozenset[str] = frozenset()
) -> RatchetResult:
    over: dict[str, tuple[int, int]] = {}
    stale: dict[str, tuple[int, int]] = {}
    unchecked: dict[str, tuple[int, int]] = {}
    for path in sorted(set(findings) | set(baseline)):
        found, allowed = findings.get(path, 0), baseline.get(path, 0)
        if found > allowed:
            over[path] = (found, allowed)
        elif found < allowed:
            (unchecked if path in incomplete else stale)[path] = (found, allowed)
    return RatchetResult(over=over, stale=stale, unchecked=unchecked)


def updated_findings(findings: Counter[str], baseline: dict[str, int], incomplete: frozenset[str]) -> Counter[str]:
    result = Counter(findings)
    for path in incomplete:
        if baseline.get(path, 0) > result.get(path, 0):
            result[path] = baseline[path]
    return result


def render_baseline(header: str, findings: Counter[str]) -> str:
    lines = [line for line in header.splitlines() if line.startswith("#")]
    lines += [f"{path} {count}" for path, count in sorted(findings.items())]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--findings", type=Path, required=True, help="semgrep --json output")
    parser.add_argument("--baseline", type=Path, required=True, help="the checked-in baseline file")
    parser.add_argument("--update", action="store_true", help="rewrite the baseline from the findings")
    args = parser.parse_args(argv)

    semgrep_output = json.loads(args.findings.read_text())
    incomplete = error_paths(semgrep_output)
    if semgrep_output.get("errors"):
        print(f"semgrep reported {len(semgrep_output['errors'])} errors. The counts can be incomplete.")
    findings = count_findings(semgrep_output)
    baseline_text = args.baseline.read_text() if args.baseline.exists() else ""
    baseline = parse_baseline(baseline_text)

    if args.update:
        findings = updated_findings(findings, baseline, incomplete)
        args.baseline.write_text(render_baseline(baseline_text, findings))
        print(f"Wrote {sum(findings.values())} findings in {len(findings)} files to {args.baseline}")
        return 0

    result = compare(findings, baseline, incomplete)
    for path, (found, allowed) in result.unchecked.items():
        print(
            f"Warning: semgrep reported an error for {path}, so its {found} findings (baseline: {allowed}) are not checked."
        )
    if result.ok:
        print(f"{sum(findings.values())} findings in {len(findings)} files. They match {args.baseline}.")
        return 0

    if result.over:
        print(f"New findings. Fix them, or add `# nosemgrep: <rule-id>` with a reason. Do not raise {args.baseline}.")
        new_paths = set(result.over)
        for item in semgrep_output.get("results", []):
            if item["path"] in new_paths:
                print(f"  {item['path']}:{item['start']['line']}: {item.get('check_id', '')}")
        for path, (found, allowed) in result.over.items():
            print(f"  {path}: {found} findings, baseline allows {allowed}")
    if result.stale:
        print(f"Fewer findings than {args.baseline} allows. Lower these lines (remove a line at 0):")
        for path, (found, allowed) in result.stale.items():
            print(f"  {path} {found}  (baseline: {allowed})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
