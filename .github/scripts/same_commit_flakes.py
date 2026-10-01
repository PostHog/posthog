#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "defusedxml~=0.7",
#   "owners-yaml",
# ]
#
# [tool.uv.sources]
# owners-yaml = { path = "../../packages/owners-yaml" }
# ///
# ruff: noqa: T201 - CLI output is the contract for this script.

from __future__ import annotations

import io
import os
import re
import sys
import json
import zipfile
import argparse
import posixpath
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import defusedxml.ElementTree as ET
from owners_yaml import OwnersResolver, first_team_owner

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "hogli-commands"))

from hogli_commands.quarantine import core as quarantine_core  # noqa: E402  # ty: ignore[unresolved-import]

GITHUB_API = "https://api.github.com"
MASTER_BRANCH = "master"
MASTER_EVENTS = frozenset({"push", "schedule"})
INCONCLUSIVE_CONCLUSIONS = frozenset({"cancelled", "skipped", "startup_failure", "stale", ""})
# A shard with this many failed tests broke as a whole (setup, OOM, a bad runner), so its failures
# say nothing about any one test and must not pair with a pass elsewhere.
MAX_FAILED_TESTS_PER_SHARD = 10
# More disagreements than this on one commit point at the environment, not at individual tests.
MAX_DISAGREEMENTS_PER_COMMIT = 5
MAX_ARTIFACT_XML_BYTES = 200 * 1024 * 1024
UNOWNED = "unowned"

_ATTEMPT_SUFFIX = re.compile(r"-attempt(\d+)$")


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class Verdict(StrEnum):
    QUARANTINE_CANDIDATE = "not quarantined yet"
    ALREADY_QUARANTINED = "already quarantined"
    SYSTEMIC = "too many disagreements on this commit to blame individual tests"


@dataclass(frozen=True)
class Suite:
    runner: str
    artifact_roots: tuple[tuple[str, str], ...]

    def jest_root_for(self, job_key: str) -> str | None:
        return next((root for prefix, root in self.artifact_roots if job_key.startswith(prefix)), None)


SUITES: dict[str, Suite] = {
    ".github/workflows/ci-frontend.yml": Suite(
        runner=quarantine_core.JEST_RUNNER,
        artifact_roots=(
            ("junit-results-frontend-", "frontend"),
            ("junit-results-replay-shared", "common/replay-shared"),
        ),
    ),
}


@dataclass(frozen=True)
class Run:
    id: int
    event: str
    head_sha: str
    html_url: str
    attempts: int = 1


@dataclass(frozen=True)
class Trial:
    run: Run
    attempt: int


@dataclass(frozen=True)
class ShardResult:
    trial: Trial
    job_key: str
    outcomes: Mapping[str, Outcome]


@dataclass(frozen=True)
class Disagreement:
    job_key: str
    test_id: str
    test_file: str
    failed_in: tuple[Trial, ...]
    passed_in: tuple[Trial, ...]


@dataclass(frozen=True)
class Finding:
    disagreement: Disagreement
    verdict: Verdict
    owner: str


@dataclass(frozen=False)
class Report:
    head_sha: str
    run_count: int = 0
    trials: list[Trial] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    skipped_artifacts: list[str] = field(default_factory=list)


class RunSource(Protocol):
    def runs_for_commit(self, workflow_path: str, head_sha: str) -> list[dict[str, Any]]: ...

    def artifacts(self, run_id: int) -> list[dict[str, Any]]: ...

    def junit_documents(self, artifact_id: int) -> list[bytes]: ...


def comparable_runs(runs: Iterable[Mapping[str, Any]], head_sha: str, repository: str) -> list[Run]:
    return [
        Run(
            id=r["id"],
            event=r["event"],
            head_sha=r["head_sha"],
            html_url=r["html_url"],
            attempts=r.get("run_attempt") or 1,
        )
        for r in runs
        if r.get("head_sha") == head_sha
        and r.get("head_branch") == MASTER_BRANCH
        and r.get("event") in MASTER_EVENTS
        and (r.get("head_repository") or {}).get("full_name") == repository
        and r.get("status") == "completed"
        and (r.get("conclusion") or "") not in INCONCLUSIVE_CONCLUSIONS
    ]


def split_attempt(artifact_name: str) -> tuple[str, int]:
    match = _ATTEMPT_SUFFIX.search(artifact_name)
    if match is None:
        return artifact_name, 1
    return artifact_name[: match.start()], int(match.group(1))


def final_outcome(testcase: Any) -> Outcome | None:
    tags = {child.tag for child in testcase}
    if "skipped" in tags:
        return None
    if "failure" in tags or "error" in tags:
        return Outcome.FAILED
    return Outcome.PASSED


def jest_test_id(file_attr: str, name: str, jest_root: str) -> tuple[str, str] | None:
    if not file_attr or not name:
        return None
    test_file = posixpath.normpath(posixpath.join(jest_root, file_attr.replace("\\", "/")))
    if test_file == ".." or test_file.startswith(("../", "/")):
        return None
    return f"{test_file}::{name}", test_file


def parse_junit(xml_documents: Iterable[bytes], jest_root: str) -> tuple[dict[str, Outcome], dict[str, str]]:
    outcomes: dict[str, Outcome] = {}
    files: dict[str, str] = {}
    for document in xml_documents:
        for testcase in ET.fromstring(document).iter("testcase"):
            identity = jest_test_id(testcase.get("file", ""), testcase.get("name", ""), jest_root)
            outcome = final_outcome(testcase)
            if identity is None or outcome is None:
                continue
            test_id, test_file = identity
            if outcomes.get(test_id) != Outcome.FAILED:
                outcomes[test_id] = outcome
            files[test_id] = test_file
    return outcomes, files


def is_shard_break(outcomes: Mapping[str, Outcome]) -> bool:
    return sum(1 for outcome in outcomes.values() if outcome == Outcome.FAILED) > MAX_FAILED_TESTS_PER_SHARD


def find_disagreements(shards: Iterable[ShardResult], test_files: Mapping[str, str]) -> list[Disagreement]:
    trials_by_test: dict[tuple[str, str], dict[Outcome, set[Trial]]] = {}
    for shard in shards:
        if is_shard_break(shard.outcomes):
            continue
        for test_id, outcome in shard.outcomes.items():
            by_outcome = trials_by_test.setdefault((shard.job_key, test_id), {})
            by_outcome.setdefault(outcome, set()).add(shard.trial)

    def ordered(trials: set[Trial]) -> tuple[Trial, ...]:
        return tuple(sorted(trials, key=lambda t: (t.run.id, t.attempt)))

    return [
        Disagreement(
            job_key=job_key,
            test_id=test_id,
            test_file=test_files.get(test_id, ""),
            failed_in=ordered(by_outcome[Outcome.FAILED]),
            passed_in=ordered(by_outcome[Outcome.PASSED]),
        )
        for (job_key, test_id), by_outcome in sorted(trials_by_test.items())
        if by_outcome.get(Outcome.FAILED) and by_outcome.get(Outcome.PASSED)
    ]


def classify(disagreements: list[Disagreement], active_entries: list[quarantine_core.Entry]) -> list[Verdict]:
    if len(disagreements) > MAX_DISAGREEMENTS_PER_COMMIT:
        return [Verdict.SYSTEMIC for _ in disagreements]
    return [
        Verdict.ALREADY_QUARANTINED
        if quarantine_core.find_match(active_entries, d.test_id) is not None
        else Verdict.QUARANTINE_CANDIDATE
        for d in disagreements
    ]


class OwnerLookup:
    def __init__(self, repo_root: Path) -> None:
        self._resolver: OwnersResolver | None
        try:
            self._resolver = OwnersResolver(repo_root)
        except Exception as exc:
            print(f"owners resolver unavailable: {exc}", file=sys.stderr)
            self._resolver = None

    def owner_of(self, test_file: str) -> str:
        if self._resolver is None or not test_file:
            return UNOWNED
        try:
            team = first_team_owner(self._resolver.resolve(test_file).owners)
        except Exception as exc:
            print(f"owners resolution failed for {test_file}: {exc}", file=sys.stderr)
            return UNOWNED
        return f"@PostHog/{team}" if team else UNOWNED


class GitHubClient:
    def __init__(self, token: str, repository: str) -> None:
        self._token = token
        self.repository = repository

    def _request(self, url: str) -> urllib.request.Request:
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        # Unredirected, because artifact downloads redirect to pre-signed blob storage URLs that
        # reject a request carrying a second credential.
        request.add_unredirected_header("Authorization", f"Bearer {self._token}")
        return request

    def get_json(self, path: str, params: Mapping[str, str | int] | None = None) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- the URL starts with the https GITHUB_API constant
        with urllib.request.urlopen(self._request(f"{GITHUB_API}{path}{query}"), timeout=30) as response:
            return json.load(response)

    def runs_for_commit(self, workflow_path: str, head_sha: str) -> list[dict[str, Any]]:
        workflow = posixpath.basename(workflow_path)
        payload = self.get_json(
            f"/repos/{self.repository}/actions/workflows/{workflow}/runs",
            {"head_sha": head_sha, "branch": MASTER_BRANCH, "per_page": 100},
        )
        return payload.get("workflow_runs", [])

    def artifacts(self, run_id: int) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self.get_json(
                f"/repos/{self.repository}/actions/runs/{run_id}/artifacts", {"per_page": 100, "page": page}
            )
            batch = payload.get("artifacts", [])
            found.extend(batch)
            if len(batch) < 100:
                return found
            page += 1

    def junit_documents(self, artifact_id: int) -> list[bytes]:
        url = f"{GITHUB_API}/repos/{self.repository}/actions/artifacts/{artifact_id}/zip"
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected -- the URL starts with the https GITHUB_API constant
        with urllib.request.urlopen(self._request(url), timeout=120) as response:
            archive = zipfile.ZipFile(io.BytesIO(response.read()))
        members = [info for info in archive.infolist() if info.filename.endswith(".xml")]
        if sum(info.file_size for info in members) > MAX_ARTIFACT_XML_BYTES:
            raise ValueError(f"JUnit files expand past {MAX_ARTIFACT_XML_BYTES} bytes")
        return [archive.read(info) for info in members]


def collect_shards(
    github: RunSource, suite: Suite, runs: list[Run]
) -> tuple[list[ShardResult], dict[str, str], list[str]]:
    shards: list[ShardResult] = []
    test_files: dict[str, str] = {}
    skipped: list[str] = []
    for run in runs:
        for artifact in github.artifacts(run.id):
            if artifact.get("expired"):
                continue
            job_key, attempt = split_attempt(artifact["name"])
            jest_root = suite.jest_root_for(job_key)
            if jest_root is None:
                continue
            try:
                outcomes, files = parse_junit(github.junit_documents(artifact["id"]), jest_root)
            except (urllib.error.URLError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
                skipped.append(f"{artifact['name']} of run {run.id}: {exc}")
                continue
            test_files.update(files)
            shards.append(ShardResult(trial=Trial(run=run, attempt=attempt), job_key=job_key, outcomes=outcomes))
    return shards, test_files, skipped


def load_active_entries(runner: str, today: date) -> list[quarantine_core.Entry]:
    return quarantine_core.active_entries(quarantine_core.load().entries, runner=runner, today=today)


def _attempt_suffix(trial: Trial) -> str:
    return f" attempt {trial.attempt}" if trial.attempt != 1 else ""


def _links(trials: tuple[Trial, ...]) -> str:
    return ", ".join(f"[{t.run.event} run {t.run.id}{_attempt_suffix(t)}]({t.run.html_url})" for t in trials)


def render_summary(report: Report) -> str:
    lines = [
        f"### Same-commit test disagreements on `{report.head_sha[:12]}`",
        "",
        f"Found {report.run_count} completed master runs of this workflow on this commit, "
        f"with {len(report.trials)} run attempts that uploaded test results.",
        "",
    ]
    if report.skipped_artifacts:
        lines.append(f"Comparison incomplete: {len(report.skipped_artifacts)} artifacts could not be read.")
        lines += [f"- {skipped}" for skipped in report.skipped_artifacts]
        lines.append("")
    if not report.findings:
        scope = "among the results it could read" if report.skipped_artifacts else "on this commit"
        lines.append(f"No test both failed and passed in the same shard {scope}.")
        return "\n".join(lines) + "\n"
    lines += ["| Test | Shard | Owner | Failed in | Passed in | Status |", "| --- | --- | --- | --- | --- | --- |"]
    for finding in report.findings:
        d = finding.disagreement
        lines.append(
            f"| `{d.test_id.replace('|', '&#124;')}` | `{d.job_key}` | {finding.owner} | {_links(d.failed_in)} | {_links(d.passed_in)} "
            f"| {finding.verdict} |"
        )
    return "\n".join(lines) + "\n"


def _escape_annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_annotations(report: Report) -> list[str]:
    annotations = []
    for finding in report.findings:
        d = finding.disagreement
        failed = ", ".join(t.run.html_url + _attempt_suffix(t) for t in d.failed_in)
        passed = ", ".join(t.run.html_url + _attempt_suffix(t) for t in d.passed_in)
        message = (
            f"{d.test_id} failed and passed in {d.job_key} on {report.head_sha[:12]} ({finding.verdict}). "
            f"Owner: {finding.owner}. Failed in {failed}. Passed in {passed}."
        )
        annotations.append(f"::warning title=Flaky test on master::{_escape_annotation(message)}")
    if report.skipped_artifacts:
        message = (
            f"Same-commit comparison on {report.head_sha[:12]} is incomplete: "
            f"{len(report.skipped_artifacts)} artifacts could not be read. See the step summary."
        )
        annotations.append(f"::warning title=Incomplete flake comparison::{_escape_annotation(message)}")
    return annotations


def compare(github: RunSource, suite: Suite, workflow_path: str, head_sha: str, repository: str) -> Report:
    report = Report(head_sha=head_sha)
    runs = comparable_runs(github.runs_for_commit(workflow_path, head_sha), head_sha, repository)
    report.run_count = len(runs)
    if sum(r.attempts for r in runs) < 2:
        return report

    shards, test_files, report.skipped_artifacts = collect_shards(github, suite, runs)
    report.trials = sorted({s.trial for s in shards}, key=lambda t: (t.run.id, t.attempt))
    disagreements = find_disagreements(shards, test_files)
    if not disagreements:
        return report

    verdicts = classify(disagreements, load_active_entries(suite.runner, datetime.now(UTC).date()))
    owners = OwnerLookup(REPO_ROOT)
    report.findings = [
        Finding(disagreement=d, verdict=verdict, owner=owners.owner_of(d.test_file))
        for d, verdict in zip(disagreements, verdicts)
    ]
    return report


def run(args: argparse.Namespace) -> Report:
    github = GitHubClient(os.environ["GITHUB_TOKEN"], args.repository)
    return compare(github, SUITES[args.workflow_path], args.workflow_path, args.head_sha, args.repository)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report tests that failed and passed on one master commit.")
    parser.add_argument(
        "--workflow-path", required=True, type=lambda value: value.split("@", 1)[0], choices=sorted(SUITES)
    )
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args(argv)

    report = run(args)
    for annotation in render_annotations(report):
        print(annotation)
    summary = render_summary(report)
    print(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
