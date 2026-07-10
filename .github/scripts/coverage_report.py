#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["diff-cover>=9,<11", "defusedxml~=0.7"]
# ///
"""Per-product backend coverage reporter.

Reads the coverage.xml files produced by the turbo-tests product matrix (one per
product, written into each product's working dir by `--cov=backend`), computes a
line-coverage percentage per touched product, and renders a bar-chart summary.

Only touched products run in CI, so whatever coverage.xml files are present *are*
the touched set — no need to be told which products changed.

Split products write partial coverage.xml across several shards; this unions the
covered line numbers per source file across all shards for a product, so the
percentage is exact rather than a per-shard average.

Render-only: this script produces the markdown report and the machine-readable
diff-cover JSON, nothing else. Posting into the shared CI report comment — and the
comment-only-when-actionable logic — lives in .github/scripts/post-coverage-section.mjs.

Near-stdlib — diff-cover for patch coverage, defusedxml for parsing artifact XML
(semgrep blocks stdlib xml parsing; artifacts are PR-controlled input).
"""

from __future__ import annotations

import os
import re
import sys
import json
import argparse
import tempfile
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# nosemgrep: python.lang.security.use-defused-xml.use-defused-xml (only used to build the output XML; all parsing goes through defusedxml)
from xml.etree import ElementTree

import defusedxml.ElementTree as DefusedElementTree

BAR_WIDTH = 20


def sanitize_path(path: str) -> str:
    """Keep artifact-derived paths inert in markdown/HTML-comment contexts."""
    return re.sub(r"[^A-Za-z0-9_./\- ]", "_", path).replace("--", "-")


@dataclass
class ProductCoverage:
    product: str
    covered: int
    valid: int

    @property
    def pct(self) -> float:
        return 100.0 * self.covered / self.valid if self.valid else 0.0


def product_from_path(xml_path: Path) -> str | None:
    """Derive the product name from a coverage XML path.

    CI stages each file as <product>.xml (the product survives upload-artifact's
    path collapse). Fall back to the .../products/<name>/coverage.xml layout for
    files read straight from a checkout.
    """
    if xml_path.stem != "coverage":
        return sanitize_path(xml_path.stem)
    parts = xml_path.parts
    if "products" in parts:
        idx = parts.index("products")
        if idx + 1 < len(parts):
            return sanitize_path(parts[idx + 1])
    return None


def _accumulate_class_lines(
    cls: ElementTree.Element, key: str, covered: dict[str, set[int]], valid: dict[str, set[int]]
) -> None:
    """Read a <class>'s <line> children into the covered/valid sets under the given key."""
    for line in cls.iter("line"):
        number_attr = line.get("number")
        if number_attr is None:
            continue
        number = int(number_attr)
        valid[key].add(number)
        if int(line.get("hits", "0")) > 0:
            covered[key].add(number)


def parse_xml(xml_path: Path, covered_lines: dict[str, set[int]], valid_lines: dict[str, set[int]]) -> None:
    """Accumulate covered / valid line numbers per source file from one coverage.xml."""
    try:
        root = DefusedElementTree.parse(xml_path).getroot()
    except ElementTree.ParseError as exc:
        sys.stderr.write(f"::warning::skipping unparseable {xml_path}: {exc}\n")
        return

    for cls in root.iter("class"):
        filename = cls.get("filename")
        if not filename:
            continue
        _accumulate_class_lines(cls, filename, covered_lines, valid_lines)


# product -> filename -> set of line numbers
LineMap = dict[str, dict[str, set[int]]]


def aggregate(artifacts_dir: Path) -> tuple[LineMap, LineMap]:
    """Union covered / valid line numbers per product per source file across all shard XMLs."""
    covered: LineMap = defaultdict(lambda: defaultdict(set))
    valid: LineMap = defaultdict(lambda: defaultdict(set))
    for xml_path in sorted(artifacts_dir.rglob("*.xml")):
        product = product_from_path(xml_path)
        if not product:
            continue
        parse_xml(xml_path, covered[product], valid[product])
    return covered, valid


def collect(covered: LineMap, valid: LineMap) -> list[ProductCoverage]:
    """Roll the per-file line sets up to one coverage figure per product."""
    results: list[ProductCoverage] = []
    for product in sorted(valid):
        total_valid = sum(len(lines) for lines in valid[product].values())
        total_covered = sum(len(lines) for lines in covered[product].values())
        results.append(ProductCoverage(product=product, covered=total_covered, valid=total_valid))
    return results


def resolve_core_path(filename: str, sources: list[str], cache: dict[str, str]) -> str:
    """Reconstruct a repo-relative path from a source-stripped core coverage filename.

    Coverage stores core filenames relative to a <source> root (e.g. ``auth.py`` under source
    ``posthog``), not repo-relative — even with relative_files. Pick the source whose joined
    path exists in the checkout; posthog wins ties since it's the bulk of core. Coverage doesn't
    tell us which source a given <class> actually came from, so when the same relative path
    exists under more than one source (e.g. an ``ee/`` file shadowing a ``posthog/`` one), the
    two classes' line data collapse into whichever source wins the tie — warn so that's visible
    instead of a silent misattribution.
    """
    if filename in cache:
        return cache[filename]
    stripped = filename.lstrip("/")
    resolved = stripped
    if not stripped.startswith(("posthog/", "ee/")):
        candidates = [
            src
            for src in sorted(sources, key=lambda s: 0 if s == "posthog" else 1)
            if src and Path(src, stripped).exists()
        ]
        if len(candidates) > 1:
            sys.stderr.write(
                f"::warning::coverage path '{stripped}' exists under multiple sources "
                f"({', '.join(candidates)}); attributing to '{candidates[0]}' — coverage may be misattributed\n"
            )
        resolved = (
            f"{candidates[0]}/{stripped}" if candidates else (f"{sources[0]}/{stripped}" if sources else stripped)
        )
    cache[filename] = resolved
    return resolved


def aggregate_core(artifacts_dir: Path) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    """Union covered / valid line numbers per file across the core (posthog/ee) coverage XMLs.

    Filenames are stored relative to their <source> root (posthog or ee); each is resolved
    back to a repo-relative path so diff-cover can match it against git diff paths.
    """
    covered: dict[str, set[int]] = defaultdict(set)
    valid: dict[str, set[int]] = defaultdict(set)
    cache: dict[str, str] = {}
    for xml_path in sorted(artifacts_dir.rglob("*.xml")):
        try:
            root = DefusedElementTree.parse(xml_path).getroot()
        except ElementTree.ParseError as exc:
            sys.stderr.write(f"::warning::skipping unparseable {xml_path}: {exc}\n")
            continue
        sources = [s.text.strip() for s in root.iter("source") if s.text and s.text.strip() not in (".", "")]
        for cls in root.iter("class"):
            filename = cls.get("filename")
            if not filename:
                continue
            repo_path = resolve_core_path(filename, sources, cache)
            _accumulate_class_lines(cls, repo_path, covered, valid)
    return covered, valid


def repo_path_for(product: str, filename: str) -> str:
    """Map a per-product coverage filename to its repo-relative path.

    turbo runs each product's backend:test with ``--cov=backend``, so coverage records
    filenames relative to ``products/<product>/backend`` (e.g. ``api.py``,
    ``migrations/0001.py``) — the ``backend/`` source root is stripped from the stored
    name. diff-cover matches against repo-relative ``git diff`` paths, so restore it.
    """
    filename = filename.lstrip("/")
    if filename == "backend" or filename.startswith("backend/"):
        return f"products/{product}/{filename}"
    return f"products/{product}/backend/{filename}"


def write_combined_cobertura(
    covered: LineMap,
    valid: LineMap,
    core_covered: dict[str, set[int]],
    core_valid: dict[str, set[int]],
    out_path: Path,
) -> None:
    """Emit one repo-relative Cobertura XML (products + core) from the unioned line sets.

    Product files are rewritten via repo_path_for(); core (posthog/ee) files are already
    repo-relative. <source> points at the repo root so diff-cover matches git diff paths.
    """
    coverage_el = ElementTree.Element("coverage", {"version": "diff-cover-combined"})
    ElementTree.SubElement(ElementTree.SubElement(coverage_el, "sources"), "source").text = "."
    classes_el = ElementTree.SubElement(
        ElementTree.SubElement(ElementTree.SubElement(coverage_el, "packages"), "package", {"name": "backend"}),
        "classes",
    )

    def add_class(repo_path: str, covered_lines: set[int], valid_lines: set[int]) -> None:
        class_el = ElementTree.SubElement(classes_el, "class", {"filename": repo_path, "name": Path(repo_path).name})
        lines_el = ElementTree.SubElement(class_el, "lines")
        for number in sorted(valid_lines):
            hit = "1" if number in covered_lines else "0"
            ElementTree.SubElement(lines_el, "line", {"number": str(number), "hits": hit})

    for product in sorted(valid):
        for filename in sorted(valid[product]):
            add_class(repo_path_for(product, filename), covered[product].get(filename, set()), valid[product][filename])
    for filename in sorted(core_valid):
        add_class(filename, core_covered.get(filename, set()), core_valid[filename])

    ElementTree.ElementTree(coverage_el).write(out_path, encoding="utf-8", xml_declaration=True)


def run_diff_cover(combined_path: Path, compare_branch: str, json_out: Path | None) -> dict | None:
    """Shell out to diff-cover and return its parsed JSON report, or None on any failure.

    Best-effort: a missing diff-cover binary, no git history, or an empty diff all just
    mean no patch section — never a hard error in a report-only job. When json_out is set
    the report is also persisted there (CI uploads it as the machine-readable payload).
    """
    with tempfile.TemporaryDirectory() as tmp:
        report = json_out if json_out is not None else Path(tmp) / "patch.json"
        extra = ["--compare-branch", compare_branch, "--format", f"json:{report}"]
        for invocation in (["diff-cover"], [sys.executable, "-m", "diff_cover.diff_cover_tool"]):
            try:
                proc = subprocess.run([*invocation, str(combined_path), *extra], capture_output=True, text=True)
            except FileNotFoundError:
                continue
            if proc.returncode != 0:
                sys.stderr.write(f"::warning::diff-cover exited {proc.returncode}: {proc.stderr.strip()}\n")
                return None
            try:
                return json.loads(Path(report).read_text())
            except (OSError, json.JSONDecodeError) as exc:
                sys.stderr.write(f"::warning::could not read diff-cover JSON: {exc}\n")
                return None
        sys.stderr.write("::warning::diff-cover not installed — skipping patch coverage\n")
        return None


def diff_touches_backend(compare_branch: str) -> bool | None:
    """Whether the diff vs compare_branch touches any measured backend path (None = can't tell).

    Used when no coverage was collected at all: a diff with no backend files means there is
    genuinely nothing to report and any stale section can be cleared, while a backend diff
    without coverage data stays undetermined (never clear a real warning on missing data).
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", f"{compare_branch}...HEAD"], capture_output=True, text=True
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        path = line.strip()
        if not path.endswith(".py"):
            continue
        if path.startswith(("posthog/", "ee/")) or (path.startswith("products/") and "/backend/" in path):
            return True
    return False


def empty_patch_data() -> dict:
    """A diff-cover-shaped payload for 'no measured backend lines changed'."""
    return {"total_num_lines": 0, "total_num_violations": 0, "total_percent_covered": 100.0, "src_stats": {}}


def bar(pct: float) -> str:
    filled = round(pct / 100 * BAR_WIDTH)
    return "█" * filled + "░" * (BAR_WIDTH - filled)


def compress_ranges(numbers: list[int]) -> list[tuple[int, int]]:
    """Collapse a line-number list into sorted (start, end) ranges."""
    nums = sorted(set(numbers))
    ranges: list[tuple[int, int]] = []
    if not nums:
        return ranges
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    return ranges


def format_line_ranges(numbers: list[int]) -> str:
    """Render line numbers as compact ranges, e.g. [408,409,410,412] -> '408–410, 412'."""
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in compress_ranges(numbers))


def render_patch_section(data: dict) -> str:
    """Render the human-facing patch-coverage block from diff-cover's JSON report."""
    total_lines = int(data.get("total_num_lines", 0))
    if not total_lines:
        return "_No measured backend lines changed in this PR (patch coverage n/a)._"

    pct = float(data.get("total_percent_covered", 0))
    violations = int(data.get("total_num_violations", 0))
    covered = total_lines - violations
    header = f"**Patch coverage** — changed backend lines (products + core): `{bar(pct)}` {pct:.1f}% ({covered:,} / {total_lines:,})"
    if not violations:
        return f"{header}\n\nAll changed backend lines are covered ✅"

    src = data.get("src_stats", {})
    rows = ["", "| File | Patch | Uncovered changed lines |", "| --- | --- | --- |"]
    for path in sorted(src, key=lambda p: src[p].get("percent_covered", 0)):
        missing = format_line_ranges(src[path].get("violation_lines", []))
        if not missing:
            continue
        rows.append(f"| `{sanitize_path(path)}` | {float(src[path].get('percent_covered', 0)):.1f}% | {missing} |")
    return header + "\n" + "\n".join(rows)


def build_agent_hint() -> str:
    """Visible steering line pointing agents at the action + the machine-readable payload."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        payload = f"the **patch-coverage** artifact on [this run]({server}/{repo}/actions/runs/{run_id}) (`gh run download {run_id} -n patch-coverage`)"
    else:
        payload = "the **patch-coverage** artifact"
    return (
        '🤖 **Agents:** add a test covering the lines above, or note why under "How did you test '
        f'this code?". Machine-readable gap list: {payload}, or the `coverage-data` block at the end of this comment.'
    )


def render_product_table(results: list[ProductCoverage]) -> list[str]:
    """Per-product absolute coverage."""
    rows = ["| Product | Coverage | Lines |", "| --- | --- | --- |"]
    for r in sorted(results, key=lambda x: x.pct):
        rows.append(f"| `{r.product}` | `{bar(r.pct)}` {r.pct:.1f}% | {r.covered:,} / {r.valid:,} |")
    return rows


def build_machine_block(patch_data: dict, results: list[ProductCoverage]) -> str:
    """A hidden, compact JSON block agents can parse straight from the comment body."""
    src = patch_data.get("src_stats", {})
    payload = {
        "patch": {
            "pct": round(float(patch_data.get("total_percent_covered", 0)), 1),
            "changed": int(patch_data.get("total_num_lines", 0)),
            "uncovered": int(patch_data.get("total_num_violations", 0)),
        },
        "uncovered_lines": {
            sanitize_path(path): [[a, b] for a, b in compress_ranges(stats.get("violation_lines", []))]
            for path, stats in src.items()
            if stats.get("violation_lines")
        },
        "products": {r.product: {"pct": round(r.pct, 1)} for r in results},
    }
    return f"<!-- coverage-data:{json.dumps(payload, separators=(',', ':'))} -->"


def render_markdown(results: list[ProductCoverage], patch_data: dict | None) -> str:
    lines = ["### 🧪 Backend test coverage", ""]
    if not results and patch_data is None:
        lines.append("_No backend coverage measured for this PR._")
        return "\n".join(lines)

    patch_section = (
        render_patch_section(patch_data) if patch_data is not None else "_Patch coverage unavailable for this run._"
    )
    lines += [patch_section, ""]

    if patch_data is not None and int(patch_data.get("total_num_violations", 0)) > 0:
        lines += [build_agent_hint(), ""]

    # Per-product table is products only — core isn't a product, and on selected-mode runs its
    # absolute number would be partial. Core still contributes to the patch section above.
    if results:
        lines += ["<details>", "<summary>Per-product line coverage (touched products)</summary>", ""]
        lines += render_product_table(results)
        lines += ["", "</details>"]

    lines += [
        "",
        "_Report-only. Patch coverage = changed backend lines covered vs `origin/master`. Sorted lowest first._",
        # Known blind spots, so "uncovered" isn't read as gospel: the Django Temporal segment runs
        # without coverage instrumentation, and core XMLs come from the PR-head tree while the diff
        # is computed on the merge ref (line drift when master touched the same core file).
        "_Known gaps: lines covered only by Temporal tests show as uncovered; core line numbers may drift if `master` changed the same file._",
    ]
    if patch_data is not None:
        lines += ["", build_machine_block(patch_data, results)]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path, help="dir holding downloaded coverage-xml-* artifacts")
    parser.add_argument("--out", type=Path, help="also write the markdown to this path")
    parser.add_argument(
        "--combined-out", type=Path, help="write a repo-relative combined Cobertura XML here (enables patch coverage)"
    )
    parser.add_argument("--compare-branch", default="origin/master", help="diff-cover compare branch")
    parser.add_argument("--patch-json-out", type=Path, help="path for diff-cover's JSON report (machine payload)")
    parser.add_argument(
        "--core-artifacts", type=Path, help="dir of core (posthog/ee) coverage-core-* artifacts to include"
    )
    args = parser.parse_args()

    covered, valid = aggregate(args.artifacts)

    core_covered: dict[str, set[int]] = {}
    core_valid: dict[str, set[int]] = {}
    if args.core_artifacts is not None and args.core_artifacts.exists():
        core_covered, core_valid = aggregate_core(args.core_artifacts)

    results = collect(covered, valid)  # per-product table is products only; core feeds patch coverage

    patch_data: dict | None = None
    if args.combined_out is not None and (results or core_valid):
        write_combined_cobertura(covered, valid, core_covered, core_valid, args.combined_out)
        patch_data = run_diff_cover(args.combined_out, args.compare_branch, args.patch_json_out)
    elif not results and not core_valid and diff_touches_backend(args.compare_branch) is False:
        # No coverage collected because nothing measured changed (e.g. a PR that dropped its
        # backend changes) — emit an explicit zero-line payload so a stale warning section
        # from an earlier run gets cleared rather than left standing.
        patch_data = empty_patch_data()
        if args.patch_json_out is not None:
            args.patch_json_out.write_text(json.dumps(patch_data))

    markdown = render_markdown(results, patch_data)

    if args.out:
        args.out.write_text(markdown)
    sys.stdout.write(markdown + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
