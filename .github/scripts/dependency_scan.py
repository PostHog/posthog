# /// script
# requires-python = "==3.12.*"
# dependencies = ["guarddog==3.2.0"]
# ///
from __future__ import annotations

import os
import re
import sys
import json
import signal
import hashlib
import tomllib
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

GUARDDOG = [sys.executable, "-m", "guarddog"]
SCAN_TIMEOUT_SECONDS = 180
SCAN_WORKERS = 8
MAX_PACKAGES = 300
BLOCKING_LABEL = "high_risk"
CLEAN_LABEL = "no_risks_detected"
NOT_SCANNED = "not_scanned"
SCANNER_PATH = ".github/scripts/dependency_scan.py"

NPM_NAME = re.compile(r"(@[A-Za-z0-9][A-Za-z0-9._~-]*/)?[A-Za-z0-9][A-Za-z0-9._~-]*")
PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
GO_MODULE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]*(/[A-Za-z0-9][A-Za-z0-9._~-]*)*")
VERSION = re.compile(r"[0-9][0-9A-Za-z.+!-]*")
GO_VERSION = re.compile(r"v[0-9][0-9A-Za-z.+-]*")
NAME_PATTERNS = {"npm": NPM_NAME, "pypi": PLAIN_NAME, "crates": PLAIN_NAME, "go": GO_MODULE}
VERSION_PATTERNS = {"npm": VERSION, "pypi": VERSION, "crates": VERSION, "go": GO_VERSION}
GO_REQUIREMENT = re.compile(r"^\s*(?:require\s+)?(\S+)\s+(v\S+)\s*(?://.*)?$")
PNPM_PACKAGE_KEY = re.compile(r"^\s+'?([^'\s]+)@([^@'\s]+)'?:\s*$")
PYPI_REGISTRY = "https://pypi.org/simple"
CRATES_REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"

EXCLUDED_RULES: dict[str, tuple[str, ...]] = {
    "npm": ("bundled_binary", "metadata_mismatch", "potentially_compromised_email_domain"),
    "pypi": ("bundled_binary", "repository_integrity_mismatch", "potentially_compromised_email_domain"),
    "crates": (),
    "go": (),
}
SCANNER_SELF_CHECK = (
    ("npm", "is-stream", "3.0.0"),
    ("pypi", "idna", "3.10"),
    ("crates", "itoa", "1.0.15"),
    ("go", "github.com/google/uuid", "v1.6.0"),
)


@dataclass(frozen=True, order=True)
class Package:
    ecosystem: str
    name: str
    version: str

    @property
    def spec(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def scannable(self) -> bool:
        return bool(
            NAME_PATTERNS[self.ecosystem].fullmatch(self.name)
            and VERSION_PATTERNS[self.ecosystem].fullmatch(self.version)
        )


@dataclass(frozen=True)
class Finding:
    package: Package
    label: str
    score: float
    rules: tuple[str, ...]


@dataclass(frozen=True)
class Location:
    path: str
    line: int


def pnpm_packages(lockfile: str) -> set[Package]:
    packages: set[Package] = set()
    in_packages = False
    for line in lockfile.splitlines():
        if line and not line[0].isspace():
            in_packages = line.rstrip() == "packages:"
        elif in_packages and (match := PNPM_PACKAGE_KEY.match(line)):
            packages.add(Package("npm", match[1], match[2]))
    return packages


def uv_packages(lockfile: str) -> set[Package]:
    return {
        Package("pypi", entry["name"], entry["version"])
        for entry in tomllib.loads(lockfile).get("package", [])
        if entry.get("source", {}).get("registry") == PYPI_REGISTRY and "version" in entry
    }


def cargo_packages(lockfile: str) -> set[Package]:
    return {
        Package("crates", entry["name"], entry["version"])
        for entry in tomllib.loads(lockfile).get("package", [])
        if entry.get("source") == CRATES_REGISTRY
    }


def go_packages(manifest: str) -> set[Package]:
    packages: set[Package] = set()
    in_require_block = False
    for line in manifest.splitlines():
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_require_block = True
        elif stripped == ")":
            in_require_block = False
        elif (in_require_block or stripped.startswith("require ")) and (match := GO_REQUIREMENT.match(line)):
            packages.add(Package("go", match[1], match[2]))
    return packages


LOCKFILE_READERS: dict[str, Callable[[str], set[Package]]] = {
    "pnpm-lock.yaml": pnpm_packages,
    "uv.lock": uv_packages,
    "Cargo.lock": cargo_packages,
    "go.mod": go_packages,
}


def added_packages(filename: str, base: str, head: str) -> set[Package]:
    read = LOCKFILE_READERS[filename]
    return read(head) - read(base)


def git(*args: str) -> str:
    command = ["git", "-c", "core.hooksPath=/dev/null", *args]
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def blob(ref: str, path: str) -> str:
    if not git("ls-tree", ref, "--", path):
        return ""
    return git("cat-file", "blob", f"{ref}:{path}")


def changed_lockfiles(base: str, head: str) -> list[str]:
    paths = git("diff", "--name-only", "--no-renames", "-z", base, head).split("\0")
    return [path for path in paths if path.rpartition("/")[2] in LOCKFILE_READERS]


def scan(package: Package) -> Finding:
    excluded = [flag for rule in EXCLUDED_RULES[package.ecosystem] for flag in ("--exclude-rules", rule)]
    command = [
        *GUARDDOG,
        package.ecosystem,
        "scan",
        package.name,
        "--version",
        package.version,
        "--output-format",
        "json",
        *excluded,
    ]
    env = {name: value for name, value in os.environ.items() if not name.startswith("GITHUB_")}
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, start_new_session=True
    )
    try:
        stdout, _ = process.communicate(timeout=SCAN_TIMEOUT_SECONDS)
        report = json.loads(stdout)
        risk = report["risk_score"]
        rules = tuple(
            sorted(rule for rule, hits in report["results"].items() if hits and not rule.startswith("capability"))
        )
        return Finding(package, str(risk["label"]), float(risk["score"]), rules)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        return Finding(package, NOT_SCANNED, 0.0, ())
    except (ValueError, KeyError, TypeError):
        return Finding(package, NOT_SCANNED, 0.0, ())


def scan_all(packages: Iterable[Package]) -> list[Finding]:
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        return list(pool.map(scan, packages))


def summary(findings: list[Finding], skipped: list[Package]) -> str:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.label] = counts.get(finding.label, 0) + 1
    lines = ["### Dependency scan", "", f"Scanned {len(findings)} added or changed packages with GuardDog.", ""]
    lines += [f"- `{label}`: {count}" for label, count in sorted(counts.items())]
    if skipped:
        lines.append(
            f"- not scanned (not a registry release, or over the {MAX_PACKAGES} package limit): {len(skipped)}"
        )
    flagged = sorted(
        (finding for finding in findings if finding.label != CLEAN_LABEL), key=lambda finding: -finding.score
    )
    if flagged:
        lines += ["", "| Package | Ecosystem | Label | Score | Rules |", "| --- | --- | --- | --- | --- |"]
        lines += [
            f"| `{finding.package.spec}` | {finding.package.ecosystem} | `{finding.label}` | {finding.score:.1f} | {', '.join(finding.rules)} |"
            for finding in flagged
        ]
    return "\n".join(lines) + "\n"


def findings_output(findings: list[Finding], skipped: list[Package]) -> str:
    flagged = sorted(
        (finding for finding in findings if finding.label != CLEAN_LABEL), key=lambda finding: -finding.score
    )
    return json.dumps(
        {
            "scanned": len(findings),
            "skipped": len(skipped),
            "flagged": [
                {
                    "ecosystem": finding.package.ecosystem,
                    "package": finding.package.spec,
                    "label": finding.label,
                    "score": finding.score,
                    "rules": list(finding.rules),
                }
                for finding in flagged
            ],
        }
    )


def line_of(lockfile: str, package: Package) -> int:
    lines = lockfile.splitlines()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if package.ecosystem == "npm":
            found = stripped.strip("':") == package.spec
        elif package.ecosystem == "go":
            found = stripped.removeprefix("require ").split("//")[0].split() == [package.name, package.version]
        else:
            following = lines[number].strip() if number < len(lines) else ""
            found = stripped == f'name = "{package.name}"' and following == f'version = "{package.version}"'
        if found:
            return number
    return 1


def sarif_output(findings: list[Finding], locations: dict[Package, Location]) -> str:
    results: list[dict[str, object]] = []
    rule_ids: set[str] = set()
    for finding in findings:
        if finding.label != BLOCKING_LABEL:
            continue
        package = finding.package
        location = locations.get(package, Location(SCANNER_PATH, 1))
        for rule in finding.rules or (BLOCKING_LABEL,):
            identity = f"{package.ecosystem}/{package.name}/{rule}"
            rule_id = f"{package.ecosystem}/{rule}"
            rule_ids.add(rule_id)
            results.append(
                {
                    "ruleId": rule_id,
                    "level": "warning",
                    "message": {
                        "text": f"{package.spec} ({package.ecosystem}) is {finding.label} with score {finding.score:.1f}: {rule}"
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": location.path},
                                "region": {"startLine": location.line},
                            }
                        }
                    ],
                    "partialFingerprints": {
                        "primaryLocationLineHash": f"{hashlib.sha256(identity.encode()).hexdigest()[:16]}:1"
                    },
                }
            )
    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "GuardDog",
                            "informationUri": "https://github.com/DataDog/guarddog",
                            "rules": [
                                {"id": rule_id, "shortDescription": {"text": f"GuardDog rule {rule_id}"}}
                                for rule_id in sorted(rule_ids)
                            ],
                        }
                    },
                    "results": results,
                }
            ],
        }
    )


def main() -> int:
    base, head = os.environ.get("BASE_REF", "HEAD^1"), os.environ.get("HEAD_REF", "HEAD")
    locations: dict[Package, Location] = {}
    for path in changed_lockfiles(base, head):
        head_lockfile = blob(head, path)
        for package in added_packages(path.rpartition("/")[2], blob(base, path), head_lockfile):
            locations.setdefault(package, Location(path, line_of(head_lockfile, package)))
    candidates = sorted(locations) or [Package(*package) for package in SCANNER_SELF_CHECK]
    scannable = [package for package in candidates if package.scannable]
    to_scan = scannable[:MAX_PACKAGES]
    skipped = [package for package in candidates if package not in to_scan]

    findings = scan_all(to_scan)
    report = summary(findings, skipped)
    sys.stdout.write(report)
    for finding in findings:
        if finding.label == BLOCKING_LABEL:
            sys.stdout.write(
                f"::warning title=Dependency scan::{finding.package.ecosystem} {finding.package.spec} is {finding.label}\n"
            )
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary_path, "a") as handle:
            handle.write(report)
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with open(output_path, "a") as handle:
            handle.write(f"findings={findings_output(findings, skipped)}\n")
            handle.write(f"sarif={sarif_output(findings, locations)}\n")
    scanner_is_broken = bool(findings) and all(finding.label == NOT_SCANNED for finding in findings)
    return 1 if scanner_is_broken else 0


if __name__ == "__main__":
    sys.exit(main())
