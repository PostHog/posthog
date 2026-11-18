from __future__ import annotations

import sys
import json
import textwrap
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).with_name("junit_node_ids.py")

SUITE = {
    "pkg/__init__.py": "",
    "pkg/sub/__init__.py": "",
    "pkg/base.py": """
        class Base:
            def test_inherited(self):
                assert False
    """,
    "pkg/test_child.py": """
        from pkg.base import Base

        class TestChild(Base):
            def test_own(self):
                pass
    """,
    "pkg/test_broken.py": """
        raise RuntimeError("import fails")
    """,
    "pkg/sub/test_mod.py": """
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("setup fails")

        def test_function_fails():
            assert False

        def test_setup_errors(broken):
            pass

        @pytest.mark.skip(reason="skips are not failures")
        def test_skipped():
            assert False

        class TestOuter:
            def test_passes(self):
                pass

            @pytest.mark.parametrize("value", ["ok", "x.y/z::w", "a b"])
            def test_param(self, value):
                assert value == "ok"

            class TestInner:
                def test_nested_fails(self):
                    assert False
    """,
}


@dataclass(frozen=True, kw_only=True, slots=True)
class Suite:
    root: Path
    report: Path
    pytest_failed_ids: set[str]


@pytest.fixture(scope="module")
def suite(tmp_path_factory: pytest.TempPathFactory) -> Suite:
    root = tmp_path_factory.mktemp("suite")
    for relative, source in SUITE.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source))
    report = root / "junit.xml"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "/dev/null",
            "--rootdir",
            str(root),
            "-o",
            "junit_family=xunit1",
            f"--junitxml={report}",
            "--continue-on-collection-errors",
            "pkg",
        ],
        cwd=root,
        capture_output=True,
        check=False,
    )
    lastfailed = json.loads((root / ".pytest_cache/v/cache/lastfailed").read_text())
    return Suite(root=root, report=report, pytest_failed_ids=set(lastfailed))


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT_PATH), *args], capture_output=True, text=True, check=False)


def test_failed_ids_match_the_ids_pytest_records_as_failed(suite: Suite) -> None:
    result = run_script("--rootdir", str(suite.root), "failed", str(suite.report))

    assert result.returncode == 0, result.stderr
    assert set(result.stdout.splitlines()) == suite.pytest_failed_ids
    assert "pkg/test_child.py::TestChild::test_inherited" in suite.pytest_failed_ids
    assert "pkg/sub/test_mod.py::TestOuter::test_param[x.y/z::w]" in suite.pytest_failed_ids
    assert "pkg/test_broken.py" in suite.pytest_failed_ids


def test_unpassed_lists_only_expected_ids_that_did_not_pass(suite: Suite, tmp_path: Path) -> None:
    expected = tmp_path / "expected.txt"
    expected.write_text(
        "pkg/sub/test_mod.py::TestOuter::test_passes\n"
        "pkg/sub/test_mod.py::TestOuter::TestInner::test_nested_fails\n"
        "pkg/sub/test_mod.py::test_skipped\n"
        "pkg/sub/test_mod.py::TestOuter::test_never_ran\n"
        "pkg/test_child.py\n"
    )

    result = run_script("--rootdir", str(suite.root), "unpassed", "--expected", str(expected), str(suite.report))

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "pkg/sub/test_mod.py::TestOuter::TestInner::test_nested_fails",
        "pkg/sub/test_mod.py::test_skipped",
        "pkg/sub/test_mod.py::TestOuter::test_never_ran",
    ]


def test_a_testcase_with_no_module_on_disk_fails_loudly(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuites><testsuite><testcase classname="gone.test_mod.TestA" name="test_x">'
        "<failure/></testcase></testsuite></testsuites>"
    )

    result = run_script("--rootdir", str(tmp_path), "failed", str(report))

    assert result.returncode == 2
    assert "::error::" in result.stderr
