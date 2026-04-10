"""Tests for product lint checks — focused on PackageJsonScriptsCheck."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hogli.product.checks import (
    CheckContext,
    PackageJsonScriptsCheck,
    _has_test_files,
    _is_noop_script,
    _parse_pytest_paths,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(
    tmp_path: Path,
    *,
    scripts: dict[str, str] | None = None,
    has_backend: bool = True,
    isolated: bool = False,
    test_files: list[str] | None = None,
    extra_dirs: list[str] | None = None,
) -> CheckContext:
    """Build a minimal product directory and return a CheckContext for it."""
    product_dir = tmp_path / "my_product"
    product_dir.mkdir()
    backend_dir = product_dir / "backend"

    if has_backend:
        backend_dir.mkdir()

    if isolated:
        (backend_dir / "facade").mkdir(parents=True, exist_ok=True)
        (backend_dir / "facade" / "contracts.py").write_text("")

    if scripts is not None:
        (product_dir / "package.json").write_text(json.dumps({"scripts": scripts}))

    if test_files:
        for tf in test_files:
            p = backend_dir / tf
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("")

    if extra_dirs:
        for d in extra_dirs:
            (product_dir / d).mkdir(parents=True, exist_ok=True)

    return CheckContext(
        name="my_product",
        product_dir=product_dir,
        backend_dir=backend_dir,
        is_isolated=isolated,
        structure={},
        detailed=False,
    )


check = PackageJsonScriptsCheck()


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestParseHelpers:
    @pytest.mark.parametrize(
        "script, expected",
        [
            ("pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short", ["backend/tests"]),
            ("pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short", ["backend/"]),
            (
                "pytest -c ../../pytest.ini --rootdir ../.. backend/ stats/tests -v --tb=short",
                ["backend/", "stats/tests"],
            ),
            ("pytest backend/test_max_tools.py", ["backend/test_max_tools.py"]),
            ("echo 'No backend tests'", []),
            ("pytest -v", []),
            ("pytest -c ../../pytest.ini --rootdir ../.. -k 'not slow' backend/tests", ["backend/tests"]),
        ],
    )
    def test_parse_pytest_paths(self, script: str, expected: list[str]) -> None:
        assert _parse_pytest_paths(script) == expected

    @pytest.mark.parametrize(
        "script, expected",
        [
            ("echo 'No backend tests'", True),
            ("echo skip", True),
            ("true", True),
            ("exit 0", True),
            (":", True),
            ("pytest backend/tests", False),
            ("pytest -v", False),
        ],
    )
    def test_is_noop_script(self, script: str, expected: bool) -> None:
        assert _is_noop_script(script) == expected

    def test_has_test_files_true(self, tmp_path: Path) -> None:
        (tmp_path / "test_foo.py").write_text("")
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_nested(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_bar.py").write_text("")
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_suffix_convention(self, tmp_path: Path) -> None:
        (tmp_path / "foo_test.py").write_text("")
        assert _has_test_files(tmp_path) is True

    def test_has_test_files_false(self, tmp_path: Path) -> None:
        (tmp_path / "models.py").write_text("")
        assert _has_test_files(tmp_path) is False

    def test_has_test_files_empty_dir(self, tmp_path: Path) -> None:
        assert _has_test_files(tmp_path) is False


# ---------------------------------------------------------------------------
# Presence checks
# ---------------------------------------------------------------------------


class TestPresenceChecks:
    def test_skip_when_no_backend_dir(self, tmp_path: Path) -> None:
        ctx = _make_product(tmp_path, has_backend=False)
        result = check.run(ctx)
        assert result.skip is True

    def test_backend_test_required_when_backend_exists(self, tmp_path: Path) -> None:
        ctx = _make_product(tmp_path, scripts={})
        result = check.run(ctx)
        assert any("missing 'backend:test'" in i for i in result.issues)

    def test_backend_test_present_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues

    def test_contract_check_required_for_isolated(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            isolated=True,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert any("missing 'backend:contract-check'" in i for i in result.issues)

    def test_contract_check_present_for_isolated_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=True,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues

    def test_invalid_json_returns_issue(self, tmp_path: Path) -> None:
        ctx = _make_product(tmp_path, has_backend=True)
        (ctx.product_dir / "package.json").write_text("{invalid json")
        result = check.run(ctx)
        assert any("not valid JSON" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Absence checks
# ---------------------------------------------------------------------------


class TestAbsenceChecks:
    def test_contract_check_forbidden_for_non_isolated(self, tmp_path: Path) -> None:
        """Non-isolated product with contract-check causes turbo-discover misclassification."""
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=False,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert any("non-isolated product" in i.lower() for i in result.issues)
        assert any("turbo-discover" in i for i in result.issues)

    def test_no_contract_check_for_non_isolated_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            isolated=False,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues


# ---------------------------------------------------------------------------
# Content checks: pytest path validation
# ---------------------------------------------------------------------------


class TestPytestPathValidation:
    def test_valid_path_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short"},
            test_files=["tests/test_foo.py"],
        )
        result = check.run(ctx)
        assert not result.issues

    def test_nonexistent_path_fails(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/typo_tests -v --tb=short"},
        )
        result = check.run(ctx)
        assert any("does not exist" in i for i in result.issues)
        assert any("typo_tests" in i for i in result.issues)

    def test_multiple_paths_one_missing(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ stats/tests -v --tb=short"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        # backend/ exists, stats/tests does not
        assert any("stats/tests" in i for i in result.issues)
        assert not any("backend/" in i for i in result.issues)

    def test_file_path_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/test_max_tools.py -v --tb=short"
            },
            test_files=["test_max_tools.py"],
        )
        result = check.run(ctx)
        assert not result.issues


# ---------------------------------------------------------------------------
# Content checks: no-op detection
# ---------------------------------------------------------------------------


class TestNoopDetection:
    def test_noop_without_test_files_passes(self, tmp_path: Path) -> None:
        """echo 'No backend tests' is fine when there are genuinely no test files."""
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "echo 'No backend tests'"},
        )
        result = check.run(ctx)
        assert not result.issues

    def test_noop_with_test_files_fails(self, tmp_path: Path) -> None:
        """echo 'No backend tests' is wrong when test files actually exist."""
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "echo 'No backend tests'"},
            test_files=["tests/test_something.py"],
        )
        result = check.run(ctx)
        assert any("no-op" in i for i in result.issues)
        assert any("test files" in i for i in result.issues)


# ---------------------------------------------------------------------------
# Content checks: || true detection
# ---------------------------------------------------------------------------


class TestPipeTrueDetection:
    def test_pipe_true_fails(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short || true"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert any("|| true" in i for i in result.issues)
        assert any("swallows" in i for i in result.issues)

    def test_pipe_exit_0_fails(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short || exit 0"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert any("|| exit 0" in i for i in result.issues)
        assert any("swallows" in i for i in result.issues)

    def test_no_pipe_true_passes(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues


# ---------------------------------------------------------------------------
# Combined scenario: isolated product, all good
# ---------------------------------------------------------------------------


class TestCombinedScenarios:
    def test_fully_valid_isolated_product(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/tests -v --tb=short",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=True,
            test_files=["tests/test_api.py"],
        )
        result = check.run(ctx)
        assert not result.issues
        assert any("✓ ok" in line for line in result.lines)

    def test_fully_valid_legacy_product(self, tmp_path: Path) -> None:
        ctx = _make_product(
            tmp_path,
            scripts={"backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/ -v --tb=short"},
            isolated=False,
            extra_dirs=["backend"],
        )
        result = check.run(ctx)
        assert not result.issues
        assert any("✓ ok" in line for line in result.lines)

    def test_multiple_issues_reported(self, tmp_path: Path) -> None:
        """A product with several problems reports all of them."""
        ctx = _make_product(
            tmp_path,
            scripts={
                "backend:test": "pytest -c ../../pytest.ini --rootdir ../.. backend/nonexistent -v --tb=short || true",
                "backend:contract-check": "echo 'Contract files unchanged'",
            },
            isolated=False,
        )
        result = check.run(ctx)
        # Should report: contract-check forbidden, || true, nonexistent path
        assert len(result.issues) >= 3
