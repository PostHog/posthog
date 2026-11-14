import sys
import json
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("dependency_scan.py")
spec = importlib.util.spec_from_file_location("dependency_scan", SCRIPT)
scanner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = scanner
spec.loader.exec_module(scanner)

PNPM_BASE = """lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      left-pad:
        specifier: ^1.3.0
        version: 1.3.0

packages:

  '@scope/kept@1.0.0':
    resolution: {integrity: sha512-aaaa}

  left-pad@1.3.0:
    resolution: {integrity: sha512-bbbb}
    peerDependencies:
      '@scope/kept': ^1.0.0

snapshots:

  left-pad@1.3.0(@scope/kept@1.0.0):
    dependencies:
      '@scope/kept': 1.0.0
"""
PNPM_HEAD = PNPM_BASE.replace(
    "  left-pad@1.3.0:\n    resolution: {integrity: sha512-bbbb}",
    "  '@scope/added@2.0.0-beta.1':\n    resolution: {integrity: sha512-cccc}\n\n"
    "  tarball-dep@https://example.com/tarball-dep.tgz:\n    resolution: {tarball: https://example.com/tarball-dep.tgz}\n\n"
    "  left-pad@1.3.1:\n    resolution: {integrity: sha512-dddd}",
).replace("left-pad@1.3.0(@scope/kept@1.0.0)", "left-pad@1.3.1(@scope/kept@1.0.0)")

UV_BASE = """version = 1

[[package]]
name = "kept"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "bumped"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "local-project"
version = "0.1.0"
source = { editable = "." }
"""
UV_HEAD = (
    UV_BASE.replace('version = "2.0.0"', 'version = "2.1.0"')
    + """
[[package]]
name = "from-git"
version = "3.0.0"
source = { git = "https://example.com/from-git.git?rev=abc#abc" }
"""
)

CARGO_BASE = """version = 4

[[package]]
name = "kept"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "workspace-member"
version = "0.1.0"
"""
CARGO_HEAD = (
    CARGO_BASE
    + """
[[package]]
name = "added"
version = "0.4.2"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "from-git"
version = "0.1.0"
source = "git+https://example.com/from-git.git#abc"
"""
)

GO_BASE = """module example.com/service

go 1.24

require (
\texample.com/kept v1.0.0
\texample.com/bumped v1.2.0 // indirect
)

replace example.com/kept => ../kept
"""
GO_HEAD = (
    GO_BASE.replace("bumped v1.2.0", "bumped v1.3.0").replace(
        "\texample.com/kept v1.0.0\n", "\texample.com/kept v1.0.0\n\texample.com/added/v2 v2.0.1\n"
    )
    + "\nrequire example.com/single v0.0.0-20260101000000-abcdefabcdef\n"
)


@pytest.mark.parametrize(
    "filename,base,head,expected",
    [
        (
            "pnpm-lock.yaml",
            PNPM_BASE,
            PNPM_HEAD,
            {
                ("npm", "@scope/added", "2.0.0-beta.1"),
                ("npm", "left-pad", "1.3.1"),
                ("npm", "tarball-dep", "https://example.com/tarball-dep.tgz"),
            },
        ),
        ("pnpm-lock.yaml", "", PNPM_BASE, {("npm", "@scope/kept", "1.0.0"), ("npm", "left-pad", "1.3.0")}),
        ("uv.lock", UV_BASE, UV_HEAD, {("pypi", "bumped", "2.1.0")}),
        ("Cargo.lock", CARGO_BASE, CARGO_HEAD, {("crates", "added", "0.4.2")}),
        (
            "go.mod",
            GO_BASE,
            GO_HEAD,
            {
                ("go", "example.com/bumped", "v1.3.0"),
                ("go", "example.com/added/v2", "v2.0.1"),
                ("go", "example.com/single", "v0.0.0-20260101000000-abcdefabcdef"),
            },
        ),
    ],
)
def test_added_packages_are_the_registry_releases_new_to_the_head_lockfile(filename, base, head, expected):
    added = scanner.added_packages(filename, base, head)

    assert {(package.ecosystem, package.name, package.version) for package in added} == expected


@pytest.mark.parametrize(
    "lockfile,package,line",
    [
        (PNPM_HEAD, ("npm", "@scope/added", "2.0.0-beta.1"), 16),
        (PNPM_HEAD, ("npm", "left-pad", "1.3.1"), 22),
        (UV_HEAD, ("pypi", "bumped", "2.1.0"), 9),
        (CARGO_HEAD, ("crates", "added", "0.4.2"), 13),
        (GO_HEAD, ("go", "example.com/bumped", "v1.3.0"), 8),
        (GO_HEAD, ("go", "example.com/single", "v0.0.0-20260101000000-abcdefabcdef"), 13),
    ],
)
def test_a_finding_points_at_the_lockfile_line_that_adds_the_package(lockfile, package, line):
    assert scanner.line_of(lockfile, scanner.Package(*package)) == line


def test_code_scanning_gets_one_result_per_rule_of_a_high_risk_package():
    flagged = scanner.Package("npm", "left-pad", "1.3.1")
    findings = [
        scanner.Finding(flagged, "high_risk", 8.0, ("npm-install-script", "shady-links")),
        scanner.Finding(scanner.Package("pypi", "bumped", "2.1.0"), "suspicious", 4.0, ("shady-links",)),
        scanner.Finding(scanner.Package("crates", "added", "0.4.2"), "not_scanned", 0.0, ()),
    ]

    run = json.loads(scanner.sarif_output(findings, {flagged: scanner.Location("pnpm-lock.yaml", 22)}))["runs"][0]

    assert [
        (result["ruleId"], result["level"], result["locations"][0]["physicalLocation"]) for result in run["results"]
    ] == [
        (rule, "warning", {"artifactLocation": {"uri": "pnpm-lock.yaml"}, "region": {"startLine": 22}})
        for rule in ("npm/npm-install-script", "npm/shady-links")
    ]


@pytest.mark.parametrize(
    "ecosystem,name,version,scannable",
    [
        ("npm", "@scope/name", "1.2.3", True),
        ("npm", "JSONStream", "1.3.5", True),
        ("pypi", "typing-extensions", "4.12.2.post1", True),
        ("crates", "serde_json", "1.0.0+build.1", True),
        ("go", "golang.org/x/net", "v0.48.0", True),
        ("go", "example.com/-flag/module", "v1.0.0", False),
        ("go", "example.com/module", "1.0.0", False),
        ("npm", "tarball-dep", "https://example.com/tarball-dep.tgz", False),
        ("npm", "--no-sandbox", "1.0.0", False),
        ("pypi", "name", "--no-sandbox", False),
        ("npm", "../outside", "1.0.0", False),
        ("pypi", "@scope/name", "1.0.0", False),
    ],
)
def test_only_a_registry_name_and_version_reach_the_scanner(ecosystem, name, version, scannable):
    assert scanner.Package(ecosystem, name, version).scannable is scannable


LEFT_PAD = scanner.Package("npm", "left-pad", "1.3.1")
TARBALL = scanner.Package("npm", "tarball-dep", "https://example.com/tarball-dep.tgz")


@pytest.mark.parametrize(
    "labels,skipped,clean",
    [
        ([], [], True),
        (["no_risks_detected", "low", "suspicious"], [], True),
        (["no_risks_detected", "high_risk"], [], False),
        (["no_risks_detected", "not_scanned"], [], False),
        (["no_risks_detected"], [TARBALL], False),
    ],
)
def test_the_gate_is_clean_only_when_every_added_package_was_scanned_below_high_risk(labels, skipped, clean):
    findings = [scanner.Finding(LEFT_PAD, label, 0.0, ()) for label in labels]

    assert scanner.is_clean(findings, skipped) is clean
