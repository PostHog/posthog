"""Ratchet on files that resolve a hostname without the out-of-band domain check.

Every host guard in this repo is IP-based, and an out-of-band interaction domain resolves to an
ordinary public IP, so a new resolver that skips the check silently restores the gap.

The check proves a file calls the matcher. It cannot prove the call runs before the resolve, so
placement stays a review matter.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
BASELINE = Path(__file__).parent / "oob_denylist_coverage_baseline.txt"
REGENERATE = "python posthog/test/repo_invariants/test_oob_denylist_coverage.py"

SCANNED_ROOTS = ("posthog", "products", "ee", "common", "nodejs/src", "rust")
SCANNED_SUFFIXES = (".py", ".ts", ".rs")
RESOLUTION_MARKERS = (
    # Python
    "getaddrinfo(",
    "gethostbyname",
    "dns.resolver",
    "dns.asyncresolver",
    # TypeScript
    "dns.lookup",
    "dns/promises",
    "node:dns",
    "resolveMx(",
    "resolve4(",
    # Rust
    "to_socket_addrs(",
    "lookup_host(",
    "TokioAsyncResolver",
    "hickory",
    "trust_dns",
)

# Each marker ends at the open paren, so only a call clears a file. A bare module name would
# also match an import, a `mod` declaration or a comment, none of which run the check.
CHECK_MARKERS = (
    "matched_oob_domain(",
    "note_oob_domain(",
    # The TypeScript mirror names the same two helpers in camel case.
    "matchedOobDomain(",
    "noteOobDomain(",
)
SKIPPED_PARTS = ("node_modules", "__pycache__", "target", "dist", "migrations")


def _is_test(path: Path) -> bool:
    name = path.name
    return name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".spec.ts")) or "tests" in path.parts


def _resolves_hostnames(text: str) -> bool:
    """Whether the file resolves a hostname and never calls the out-of-band check."""
    return any(marker in text for marker in RESOLUTION_MARKERS) and not any(marker in text for marker in CHECK_MARKERS)


def collect() -> list[str]:
    found: set[str] = set()
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*"):
            if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
                continue
            if any(part in SKIPPED_PARTS for part in path.parts) or _is_test(path):
                continue
            if _resolves_hostnames(path.read_text(errors="ignore")):
                found.add(str(path.relative_to(REPO_ROOT)))
    return sorted(found)


def test_naming_the_check_without_calling_it_does_not_exempt_a_resolver() -> None:
    resolve = "(host, 0).to_socket_addrs()"
    assert _resolves_hostnames(f"use common_dns::oob_domains;\n{resolve}")
    assert _resolves_hostnames(f"pub mod oob_domains;\n{resolve}")
    assert not _resolves_hostnames(f'note_oob_domain(host, "g", None);\n{resolve}')
    assert not _resolves_hostnames(f"noteOobDomain(host, 'g', ctx);\n{resolve}")


def test_resolvers_match_the_baseline() -> None:
    scanned = collect()
    recorded = sorted(line for line in BASELINE.read_text().splitlines() if line.strip())
    if scanned == recorded:
        return
    added = [line for line in scanned if line not in recorded]
    removed = [line for line in recorded if line not in scanned]
    report = "\n".join([*(f"  + {line}" for line in added), *(f"  - {line}" for line in removed)])
    raise AssertionError(
        "oob_denylist_coverage_baseline.txt no longer matches the repo.\n"
        "A '+' line resolves a hostname and does not reference the out-of-band domain check. "
        "Call the check before the resolve. Do not add the line to the baseline: the list may only get shorter.\n"
        f"A '-' line means a file was fixed. The file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )


if __name__ == "__main__":
    BASELINE.write_text("\n".join(collect()) + "\n")
    sys.stdout.write(f"{BASELINE.name} written\n")
