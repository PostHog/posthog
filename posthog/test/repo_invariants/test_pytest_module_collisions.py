"""Guard against test files that one pytest session cannot collect together.

Under pytest's default ``prepend`` import mode a module is named by walking up from
its file while ``__init__.py`` exists (``_pytest.pathlib.resolve_package_path``: "the
last directory upwards which still contains an __init__.py"). Two files that land on
the same dotted name are one module to ``sys.modules``, so pytest rejects the second
with ``import file mismatch``. That is a collection error, not a skip: the session
stops and exits 2, and nothing in it runs.
https://docs.pytest.org/en/stable/explanation/pythonpath.html

Two files only collide if one session collects both. CI never runs the whole repo at
once - Core takes posthog/ee, Temporal takes posthog/temporal plus three product
subtrees, and every other product runs alone under turbo. So this checks each session
separately. A shared basename across two sessions is fine and always has been; the
repo has many.

Inside a session, sharding decides whether a collision fires. A full sharded run
passes ``--split-granularity=file``, and pytest-split then gates each file before
import (``PytestSplitFilePlugin.pytest_ignore_collect``), so a pair only meets when
the plan puts both in one shard. Every other path imports both:

* selected mode, the usual one on a PR, runs ``pytest $FILES`` with no splitting at
  all, so any diff whose selection reaches both files kills the job;
* the item-granularity fallback ci-backend.yml keeps for unrebased PRs;
* any run by hand of the same paths.

``--import-mode=importlib`` would drop the uniqueness requirement everywhere and make
this whole class of bug impossible. That changes import semantics for every test, so
it belongs in its own change rather than in a guard.

Regenerate the baseline (only to ratchet DOWN, after fixing a collision):

    python posthog/test/repo_invariants/test_pytest_module_collisions.py
"""

import re
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTEST_INI = REPO_ROOT / "pytest.ini"
BASELINE = Path(__file__).with_name("pytest_module_collisions_baseline.txt")

# pytest's default `python_files` and `norecursedirs`; this repo overrides neither.
TEST_FILE_GLOBS = ("test_*.py", "*_test.py")
NORECURSEDIRS = ("*.egg", ".*", "_darcs", "build", "CVS", "dist", "node_modules", "venv", "{arch}")

# The pytest invocations CI actually runs, each one its own sys.modules. Core, Temporal
# and POE mirror the positional arguments in ci-backend.yml ("Run Core tests" / "Run
# Temporal tests"); the tool sessions mirror ci-python.yml. Products get one session
# each because turbo runs them from products/<name>/. Widen a session here when the
# workflow widens one, or this stops matching what CI collects.
CI_SESSIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "core": (("posthog", "ee"), ("posthog/temporal", "posthog/dags", "posthog/test/repo_invariants")),
    "temporal": (
        (
            "posthog/temporal",
            "products/batch_exports/backend/tests/temporal",
            "products/tasks/backend/temporal",
            "products/signals/backend/emission",
        ),
        (),
    ),
    "core-poe": (
        (
            "posthog/clickhouse",
            "posthog/queries",
            "products/product_analytics/backend/tests/api",
            "posthog/api/test/dashboards",
            "ee/clickhouse",
        ),
        ("posthog/hogql_queries", "posthog/hogql"),
    ),
    "repo-invariants": (("posthog/test/repo_invariants",), ()),
    "tool:hogli": (("tools/hogli/tests",), ()),
    "tool:hogli-commands": (("tools/hogli-commands",), ()),
    "tool:owners": (("tools/owners/tests",), ()),
    "tool:query-performance-ai": (("tools/query-performance-ai",), ()),
    "tool:pr-approval-agent": (("tools/pr-approval-agent",), ()),
    "tool:dependency-detection": (("bin/test",), ()),
}


def _ini_ignores() -> tuple[str, ...]:
    """The --ignore paths in pytest.ini addopts, which apply to every session."""
    return tuple(re.findall(r"--ignore=(\S+)", PYTEST_INI.read_text()))


def _sessions() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    sessions = dict(CI_SESSIONS)
    # turbo runs each product on its own. Scoping to products/<name> is a superset of the
    # per-product backend:test target, which keeps a new product covered without parsing
    # every package.json.
    for directory in sorted((REPO_ROOT / "products").iterdir()):
        if directory.is_dir() and not directory.name.startswith("."):
            sessions.setdefault(f"product:{directory.name}", ((f"products/{directory.name}",), ()))
    return sessions


def _module_name(path: Path) -> str:
    """Reproduce pytest prepend-mode naming: walk up while __init__.py exists."""
    parts = [path.stem]
    directory = path.parent
    while (directory / "__init__.py").exists() and directory != REPO_ROOT:
        parts.append(directory.name)
        directory = directory.parent
    return ".".join(reversed(parts))


def _test_files() -> dict[str, str]:
    found = {}
    for path in REPO_ROOT.rglob("*.py"):
        if not any(path.match(glob) for glob in TEST_FILE_GLOBS):
            continue
        if any(fnmatch(part, pattern) for part in path.parts for pattern in NORECURSEDIRS):
            continue
        found[str(path.relative_to(REPO_ROOT))] = _module_name(path)
    return found


def _active_ini_ignores(targets: tuple[str, ...]) -> tuple[str, ...]:
    """An --ignore in pytest.ini does not override a path named on the command line.

    ci-python.yml runs `pytest tools/hogli/tests` even though addopts carries
    --ignore=tools/hogli, and those tests do collect. So an ignore only bites a session
    that does not point inside it.
    """
    return tuple(
        ignore
        for ignore in _ini_ignores()
        if not any(target == ignore or target.startswith(f"{ignore}/") for target in targets)
    )


def _collect() -> dict[str, list[str]]:
    """Colliding files keyed by "<session> :: <module name>"."""
    files = _test_files()
    collisions: dict[str, list[str]] = {}
    for session, (targets, ignores) in sorted(_sessions().items()):
        skipped = ignores + _active_ini_ignores(targets)
        by_module: dict[str, list[str]] = {}
        for relative, module in files.items():
            if not any(relative == t or relative.startswith(f"{t}/") for t in targets):
                continue
            if any(relative == i or relative.startswith(f"{i}/") for i in skipped):
                continue
            by_module.setdefault(module, []).append(relative)
        for module, paths in by_module.items():
            if len(paths) > 1:
                collisions[f"{session} :: {module}"] = sorted(paths)
    return collisions


def _format(collisions: dict[str, list[str]]) -> list[str]:
    return sorted(f"{key}: {', '.join(paths)}" for key, paths in collisions.items())


def test_no_new_pytest_module_name_collisions() -> None:
    current = set(_format(_collect()))
    baseline = {line.strip() for line in BASELINE.read_text().splitlines() if line.strip() and not line.startswith("#")}

    new = sorted(current - baseline)
    assert not new, (
        "These test files share a pytest module name inside one CI session, so that "
        "session stops at collection with `import file mismatch` and runs nothing:\n\n  "
        + "\n  ".join(new)
        + "\n\nUsually a test directory is missing its `__init__.py` while its parent has one. "
        "Adding the marker fixes every basename in that directory at once; renaming the "
        "colliding module only fixes the one. Verify with:\n"
        "  pytest --collect-only <the listed paths>\n"
    )

    fixed = sorted(baseline - current)
    assert not fixed, (
        "These collisions are fixed - ratchet the baseline down so they cannot come back: "
        "python posthog/test/repo_invariants/test_pytest_module_collisions.py\n\n  " + "\n  ".join(fixed)
    )


BASELINE_HEADER = (
    "# Test files that share a pytest module name inside one CI session. That session dies\n"
    "# at collection and runs nothing, so this list should stay empty.\n"
    "# Maintained by test_no_new_pytest_module_name_collisions - regenerate with:\n"
    "#   python posthog/test/repo_invariants/test_pytest_module_collisions.py\n"
)


def write_baseline(collisions: dict[str, list[str]]) -> None:
    BASELINE.write_text(BASELINE_HEADER + "\n".join(_format(collisions)) + "\n")


if __name__ == "__main__":
    found = _collect()
    write_baseline(found)
    print(f"baseline written: {len(found)} collision(s)")  # noqa: T201
