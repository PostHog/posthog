#!/usr/bin/env python3
# ruff: noqa: T201 allow print statements
"""Split one semgrep report into the verdicts that the semgrep-devex job enforces.

The job needs three verdicts from the devex rules over the same tree, and it used to run
`semgrep` once for each. A `semgrep` run starts from a cold cache, because the container is
discarded afterwards, so every verdict parsed the tree again. The job now scans once with
`--json` and calls this script for each verdict:

    backlog        print the WARNING-severity findings, as the informational step printed them
    errors         fail on an ERROR-severity finding outside the given path prefixes
    ratchet-input  write the findings of one rule under the given --path prefixes, in the
                   shape that bin/semgrep_ratchet.py reads
"""

import sys
import json
import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# The informational pass lists the backlog of the WARNING rules. An ERROR finding is either
# blocking, or under an excluded prefix where it is knowingly accepted, so it stays out.
BACKLOG_SEVERITIES = frozenset({"WARNING"})


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def severity(result: dict[str, Any]) -> str:
    return result.get("extra", {}).get("severity", "")


def selected_results(report: dict[str, Any], severities: Iterable[str]) -> list[dict[str, Any]]:
    wanted = frozenset(severities)
    return [result for result in report.get("results", []) if severity(result) in wanted]


def under_any(path: str, prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in prefixes)


def finding_line(result: dict[str, Any]) -> str:
    path = result.get("path", "")
    line = result.get("start", {}).get("line", "")
    return f"{path}:{line}: {severity(result)} {result.get('check_id', '')}"


def describe(result: dict[str, Any]) -> str:
    message = result.get("extra", {}).get("message", "").strip().splitlines()
    return message[0] if message else ""


def print_backlog(report: dict[str, Any]) -> int:
    scanned = report.get("paths", {}).get("scanned")
    if scanned is not None:
        print(f"Scanned {len(scanned)} files.")
    findings = sorted(
        selected_results(report, BACKLOG_SEVERITIES),
        key=lambda result: (severity(result), result.get("path", ""), result.get("start", {}).get("line", 0)),
    )
    counts = {
        level: sum(1 for finding in findings if severity(finding) == level) for level in sorted(BACKLOG_SEVERITIES)
    }
    print(f"Findings by severity: {counts}")
    for finding in findings:
        print(finding_line(finding), "-", describe(finding))
        for line in finding.get("extra", {}).get("lines", "").strip().splitlines()[:3]:
            print("   |", line)
    print("This pass reports the backlog. It does not fail the job.")
    return 0


def check_errors(report: dict[str, Any], excluded: Iterable[str]) -> int:
    excluded = tuple(excluded)
    findings = sorted(
        (result for result in selected_results(report, ["ERROR"]) if not under_any(result.get("path", ""), excluded)),
        key=lambda result: (result.get("path", ""), result.get("start", {}).get("line", 0)),
    )
    if not findings:
        print(f"No ERROR-severity findings outside {list(excluded)}.")
        return 0
    for finding in findings:
        print(finding_line(finding), "-", describe(finding))
        for line in finding.get("extra", {}).get("lines", "").strip().splitlines()[:3]:
            print("   |", line)
    print(f"{len(findings)} ERROR-severity findings. Fix them, or add `# nosemgrep: <rule-id>` with a reason.")
    return 1


def names_rule(check_id: str, rule_id: str) -> bool:
    # A rule read from a config directory is reported under a dotted path, such as
    # `semgrep.rules.devex.integration-model-through-sdk`.
    return check_id == rule_id or check_id.endswith("." + rule_id)


def ratchet_input(report: dict[str, Any], rule_id: str, prefixes: Iterable[str]) -> dict[str, Any]:
    prefixes = tuple(prefixes)
    results = [
        result
        for result in report.get("results", [])
        if names_rule(result.get("check_id", ""), rule_id) and under_any(result.get("path", ""), prefixes)
    ]
    errors = []
    for error in report.get("errors", []):
        paths = [error.get("path")] + [span.get("file") for span in error.get("spans") or []]
        if any(path and under_any(path, prefixes) for path in paths):
            errors.append(error)
    return {"results": results, "errors": errors}


def write_ratchet_input(report: dict[str, Any], rule_id: str, prefixes: Iterable[str], output: Path) -> int:
    extracted = ratchet_input(report, rule_id, prefixes)
    output.write_text(json.dumps(extracted, indent=2) + "\n")
    print(f"Wrote {len(extracted['results'])} `{rule_id}` findings to {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["backlog", "errors", "ratchet-input"])
    parser.add_argument("--findings", type=Path, required=True, help="semgrep --json output")
    parser.add_argument("--exclude", action="append", default=[], help="path prefix to leave out of the errors check")
    parser.add_argument("--rule", default="", help="rule id to keep for ratchet-input")
    parser.add_argument("--output", type=Path, help="where ratchet-input writes its JSON")
    parser.add_argument("--path", action="append", default=[], help="path prefix to keep for ratchet-input")
    args = parser.parse_args(argv)
    report = load_report(args.findings)

    if args.command == "backlog":
        return print_backlog(report)
    if args.command == "errors":
        return check_errors(report, args.exclude)
    if not args.output or not args.rule or not args.path:
        parser.error("ratchet-input needs --rule, --output and at least one --path")
    return write_ratchet_input(report, args.rule, args.path, args.output)


if __name__ == "__main__":
    sys.exit(main())
