from __future__ import annotations

import sys
import shutil
import importlib.util
from pathlib import Path

import pytest

import coverage

SCRIPT_PATH = Path(__file__).with_name("coverage_report.py")
SPEC = importlib.util.spec_from_file_location("coverage_report", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
coverage_report = importlib.util.module_from_spec(SPEC)
sys.modules["coverage_report"] = coverage_report
SPEC.loader.exec_module(coverage_report)


# ---------- product_from_path ----------


@pytest.mark.parametrize(
    "xml_path,expected",
    [
        (Path("cov-artifacts/product_analytics.xml"), "product_analytics"),
        (Path("products/error_tracking/coverage.xml"), "error_tracking"),
        (Path("coverage.xml"), None),
        (Path("cov-artifacts/weird;name.xml"), "weird_name"),
        (Path("products/weird;name/coverage.xml"), "weird_name"),
    ],
)
def test_product_from_path(xml_path: Path, expected: str | None) -> None:
    assert coverage_report.product_from_path(xml_path) == expected


# ---------- repo_path_for ----------


@pytest.mark.parametrize(
    "product,filename,expected",
    [
        ("error_tracking", "api.py", "products/error_tracking/backend/api.py"),
        ("error_tracking", "migrations/0001.py", "products/error_tracking/backend/migrations/0001.py"),
        ("error_tracking", "backend/api.py", "products/error_tracking/backend/api.py"),
        ("error_tracking", "backend", "products/error_tracking/backend"),
    ],
)
def test_repo_path_for(product: str, filename: str, expected: str) -> None:
    assert coverage_report.repo_path_for(product, filename) == expected


# ---------- convert_product_data / convert_core_data ----------


def _write_shards(artifacts: Path, data_file_name: str, shards: list[dict[str, set[int]]]) -> None:
    for shard, executed in enumerate(shards):
        shard_dir = artifacts / f"shard-{shard}"
        shard_dir.mkdir(parents=True)
        data = coverage.CoverageData(basename=str(shard_dir / data_file_name))
        data.add_lines(executed)
        data.write()


def test_convert_product_data_combines_shards_under_repo_paths(tmp_path: Path) -> None:
    source = tmp_path / "products" / "links" / "backend" / "api.py"
    source.parent.mkdir(parents=True)
    source.write_text("def a():\n    return 1\n\n\ndef b():\n    return 2\n")
    shard_source = "/home/runner/work/posthog/posthog/products/links/backend/api.py"
    artifacts = tmp_path / "cov-artifacts"
    _write_shards(artifacts, "links.coverage", [{shard_source: {1, 2, 5}}, {shard_source: {1, 5}}])

    coverage_report.convert_product_data(artifacts, tmp_path)
    covered, valid = coverage_report.aggregate(artifacts)

    assert [coverage_report.repo_path_for("links", f) for f in valid["links"]] == ["products/links/backend/api.py"]
    assert coverage_report.collect(covered, valid) == [coverage_report.ProductCoverage("links", covered=3, valid=4)]


def test_convert_core_data_combines_both_roots_under_the_core_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".github").mkdir()
    shutil.copy(SCRIPT_PATH.parent.parent / "coverage-core.cfg", tmp_path / ".github" / "coverage-core.cfg")
    for source in ("posthog/api/auth.py", "ee/api/auth.py"):
        (tmp_path / source).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / source).write_text("x = 1\ny = 2\n")
    core_artifacts = tmp_path / "core-artifacts"
    shards = [{"posthog/api/auth.py": {1}}, {"posthog/api/auth.py": {2}, "ee/api/auth.py": {1}}]
    _write_shards(core_artifacts, ".coverage", shards)

    coverage_report.convert_core_data(core_artifacts)
    covered, valid = coverage_report.aggregate_core(core_artifacts)

    assert {path: sorted(lines) for path, lines in covered.items()} == {
        "posthog/api/auth.py": [1, 2],
        "ee/api/auth.py": [1],
    }
    assert sorted(valid) == ["ee/api/auth.py", "posthog/api/auth.py"]


# ---------- resolve_core_path ----------


def test_resolve_core_path_passes_through_already_rooted_filenames() -> None:
    assert coverage_report.resolve_core_path("posthog/api/auth.py", ["posthog", "ee"], {}) == "posthog/api/auth.py"


def test_resolve_core_path_resolves_against_the_owning_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ee" / "api").mkdir(parents=True)
    (tmp_path / "ee" / "api" / "only_in_ee.py").touch()

    assert coverage_report.resolve_core_path("api/only_in_ee.py", ["posthog", "ee"], {}) == "ee/api/only_in_ee.py"


def test_resolve_core_path_falls_back_to_first_source_when_no_candidate_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert coverage_report.resolve_core_path("nowhere.py", ["posthog", "ee"], {}) == "posthog/nowhere.py"


def test_resolve_core_path_warns_and_prefers_posthog_when_a_path_collides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A relative path that exists under both roots can't be disambiguated from the coverage
    # XML alone — this is the silent-misattribution case the qa-swarm/codex reviews flagged.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "posthog" / "api").mkdir(parents=True)
    (tmp_path / "posthog" / "api" / "authentication.py").touch()
    (tmp_path / "ee" / "api").mkdir(parents=True)
    (tmp_path / "ee" / "api" / "authentication.py").touch()

    resolved = coverage_report.resolve_core_path("api/authentication.py", ["ee", "posthog"], {})

    assert resolved == "posthog/api/authentication.py"
    assert "::warning::" in capsys.readouterr().err


def test_resolve_core_path_caches_by_filename() -> None:
    cache: dict[str, str] = {"api/auth.py": "ee/api/auth.py"}
    assert coverage_report.resolve_core_path("api/auth.py", ["posthog"], cache) == "ee/api/auth.py"


# ---------- compress_ranges / format_line_ranges ----------


@pytest.mark.parametrize(
    "numbers,expected",
    [
        ([], []),
        ([5], [(5, 5)]),
        ([1, 2, 3], [(1, 3)]),
        ([408, 409, 410, 412], [(408, 410), (412, 412)]),
        ([3, 1, 2], [(1, 3)]),  # unsorted input, duplicates collapse via set()
    ],
)
def test_compress_ranges(numbers: list[int], expected: list[tuple[int, int]]) -> None:
    assert coverage_report.compress_ranges(numbers) == expected


@pytest.mark.parametrize(
    "numbers,expected",
    [
        ([], ""),
        ([408, 409, 410, 412], "408–410, 412"),
        ([5], "5"),
    ],
)
def test_format_line_ranges(numbers: list[int], expected: str) -> None:
    assert coverage_report.format_line_ranges(numbers) == expected


# ---------- diff_touches_backend ----------


@pytest.mark.parametrize(
    "changed_files,expected",
    [
        (["frontend/src/scene.tsx", "docs/readme.md"], False),  # frontend-only PR → safe to clear stale section
        (["posthog/api/auth.py"], True),
        (["ee/api/auth.py"], True),
        (["products/error_tracking/backend/api.py"], True),
        (["products/error_tracking/frontend/scene.tsx"], False),  # product frontend is not measured
        (["posthog/README.md"], False),  # non-.py under a backend root is not measured
        ([], False),
    ],
)
def test_diff_touches_backend(monkeypatch: pytest.MonkeyPatch, changed_files: list[str], expected: bool) -> None:
    def fake_run(*args: object, **kwargs: object) -> object:
        class Proc:
            returncode = 0
            stdout = "\n".join(changed_files)

        return Proc()

    monkeypatch.setattr(coverage_report.subprocess, "run", fake_run)
    assert coverage_report.diff_touches_backend("origin/master") is expected


def test_diff_touches_backend_is_undetermined_when_git_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    # Undetermined (not False) on git failure — False would clear a possibly-real warning.
    def fake_run(*args: object, **kwargs: object) -> object:
        class Proc:
            returncode = 128
            stdout = ""

        return Proc()

    monkeypatch.setattr(coverage_report.subprocess, "run", fake_run)
    assert coverage_report.diff_touches_backend("origin/master") is None
