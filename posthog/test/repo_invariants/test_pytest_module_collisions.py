"""Guard against test files that pytest cannot collect together.

Under pytest's default ``prepend`` import mode a test module is named by walking up
from its file while ``__init__.py`` exists, so two files whose walk-up lands on the
same dotted name are the same module as far as ``sys.modules`` is concerned. pytest
rejects the second one with ``import file mismatch``.

That is a collection error, not a skip. The session stops on it and exits 2, so
*nothing* in that run executes, not just the colliding file. The upstream rule is
explicit: without packages "each test file needs to have a unique name compared to
the other test files, otherwise pytest will raise an error".
https://docs.pytest.org/en/stable/explanation/pythonpath.html

The walk-up is ``_pytest.pathlib.resolve_package_path``: "the last directory upwards
which still contains an __init__.py". This repo overrides neither ``--import-mode``
(default ``prepend``) nor ``consider_namespace_packages`` (default false), so that
naming is what a session here actually does. ``--import-mode=importlib`` drops the
uniqueness requirement altogether, but that is a repo-wide import-semantics change
and not one to make from inside a guard.

CI never hits the error, because the Core backend lane collects ``posthog``/``ee``
while ``products/*`` run under separate turbo lanes. No lane spans both trees, so
the breakage waits for whoever runs them together.

Regenerate the baseline (only to ratchet DOWN, after fixing a collision):

    python posthog/test/repo_invariants/test_pytest_module_collisions.py
"""

import re
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTEST_INI = REPO_ROOT / "pytest.ini"
BASELINE = Path(__file__).with_name("pytest_module_collisions_baseline.txt")

# pytest's default `python_files`; this repo does not override it.
TEST_FILE_GLOBS = ("test_*.py", "*_test.py")

# pytest's `norecursedirs` default, which this repo does not override. Matching it keeps the
# scan to directories a real session actually descends into.
NORECURSEDIRS = ("*.egg", ".*", "_darcs", "build", "CVS", "dist", "node_modules", "venv", "{arch}")


def _ignored_roots() -> set[Path]:
    """The --ignore paths pytest.ini already excludes, so this mirrors a real session."""
    addopts = PYTEST_INI.read_text()
    return {REPO_ROOT / p for p in re.findall(r"--ignore=(\S+)", addopts)}


def _module_name(path: Path) -> str:
    """Reproduce pytest prepend-mode naming: walk up while __init__.py exists."""
    parts = [path.stem]
    directory = path.parent
    while (directory / "__init__.py").exists() and directory != REPO_ROOT:
        parts.append(directory.name)
        directory = directory.parent
    return ".".join(reversed(parts))


def _collect() -> dict[str, list[str]]:
    ignored = _ignored_roots()
    by_module: dict[str, list[str]] = {}
    for path in REPO_ROOT.rglob("*.py"):
        if not any(path.match(glob) for glob in TEST_FILE_GLOBS):
            continue
        if any(fnmatch(part, pattern) for part in path.parts for pattern in NORECURSEDIRS):
            continue
        if any(root in path.parents for root in ignored):
            continue
        by_module.setdefault(_module_name(path), []).append(str(path.relative_to(REPO_ROOT)))
    return {module: sorted(files) for module, files in by_module.items() if len(files) > 1}


def _format(collisions: dict[str, list[str]]) -> list[str]:
    return sorted(f"{module}: {', '.join(files)}" for module, files in collisions.items())


def test_no_new_pytest_module_name_collisions() -> None:
    current = set(_format(_collect()))
    baseline = {line.strip() for line in BASELINE.read_text().splitlines() if line.strip() and not line.startswith("#")}

    new = sorted(current - baseline)
    assert not new, (
        "These test files resolve to the same pytest module name. Any run that collects more "
        "than one of them stops with `import file mismatch` and executes nothing:\n\n  "
        + "\n  ".join(new)
        + "\n\nUsually the directory is a test subpackage missing its `__init__.py` while its "
        "parent has one. Adding the marker fixes every basename in that directory at once; "
        "renaming the colliding module only fixes the one. Verify with:\n"
        "  pytest --collect-only <the listed paths>\n"
    )

    fixed = sorted(baseline - current)
    assert not fixed, (
        "These collisions are fixed — ratchet the baseline down so they cannot come back: "
        "python posthog/test/repo_invariants/test_pytest_module_collisions.py\n\n  " + "\n  ".join(fixed)
    )


BASELINE_HEADER = (
    "# pytest module-name collisions that predate the invariant guarding them.\n"
    "# Each line is a set of test files that resolve to one module name. A run that collects\n"
    "# more than one of them dies at collection. Shrink this list; never grow it.\n"
    "# Maintained by test_no_new_pytest_module_name_collisions — regenerate with:\n"
    "#   python posthog/test/repo_invariants/test_pytest_module_collisions.py\n"
)


def write_baseline(collisions: dict[str, list[str]]) -> None:
    BASELINE.write_text(BASELINE_HEADER + "\n".join(_format(collisions)) + "\n")


if __name__ == "__main__":
    found = _collect()
    write_baseline(found)
    print(f"baseline written: {len(found)} colliding module name(s)")  # noqa: T201
