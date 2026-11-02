"""A test body must wait on a condition, never on a fixed `time.sleep`.

A fixed sleep guesses how long the work takes: it flakes on a loaded CI runner and
slows every run on a fast one. Replace it with the control that matches the wait:

- Clock-driven logic (TTL, expiry, backoff): `time_machine.travel(..., tick=False)`
  and `traveller.shift(...)`. time-machine does not patch `time.monotonic()`, so
  inject a clock into code that reads it.
- Work on another thread or process: wait on a signal it sets (`threading.Event`,
  a future, `thread.join()`), or poll the observable state in a loop with a deadline.
- Ordering between two writes: set each write's timestamp explicitly.

A sleep inside a loop (a poll) or inside a nested function (a fake that simulates a
slow dependency) is allowed, because there the delay is not what the test waits on.
"""

import ast
import subprocess
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).parents[3]
SCANNED_ROOTS = ("bin", "common", "ee", "posthog", "products", "services", "tools")
TEST_FUNCTION_PREFIXES = ("test", "setUp", "tearDown", "setup_method", "teardown_method")
NOT_A_TEST_BODY = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ClassDef,
    ast.While,
    ast.For,
    ast.AsyncFor,
)


def _is_test_file(path: Path) -> bool:
    return (
        path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or path.name == "conftest.py"
        or not {"test", "tests"}.isdisjoint(path.parts[:-1])
    )


def _sleep_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    module_aliases: set[str] = set()
    function_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "time")
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            function_aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "sleep")
    return module_aliases, function_aliases


def _body_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    pending: list[ast.AST] = list(function.body)
    while pending:
        node = pending.pop()
        if isinstance(node, NOT_A_TEST_BODY):
            continue
        yield node
        pending.extend(ast.iter_child_nodes(node))


def sleeps_in_test_bodies(source: str) -> list[int]:
    tree = ast.parse(source)
    module_aliases, function_aliases = _sleep_names(tree)
    if not module_aliases and not function_aliases:
        return []
    lines = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not function.name.startswith(TEST_FUNCTION_PREFIXES):
            continue
        for node in _body_nodes(function):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "sleep"
                and isinstance(target.value, ast.Name)
                and target.value.id in module_aliases
            ) or (isinstance(target, ast.Name) and target.id in function_aliases):
                lines.append(node.lineno)
    return sorted(lines)


def collect_offenders() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", *(f"{root}/*.py" for root in SCANNED_ROOTS)],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.split("\0")
    offenders: list[str] = []
    for relative in filter(None, tracked):
        path = REPO_ROOT / relative
        if not _is_test_file(path):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if "sleep" not in source:
            continue
        offenders.extend(f"{relative}:{line}" for line in sleeps_in_test_bodies(source))
    return offenders


def test_detection() -> None:
    source = """
import time
from time import sleep as pause

def test_waits():
    time.sleep(1)
    pause(1)

class TestCase:
    def setUp(self):
        time.sleep(1)

def test_polls():
    while not ready():
        time.sleep(0.05)
    for _ in range(3):
        time.sleep(0.05)

def test_fakes_a_slow_dependency():
    def slow():
        time.sleep(1)
    run(slow)

def helper():
    time.sleep(1)
"""
    assert sleeps_in_test_bodies(source) == [6, 7, 11]


def test_no_sleep_in_test_bodies() -> None:
    offenders = collect_offenders()
    assert not offenders, (
        "Fixed time.sleep in a test body. Read the docstring of "
        "posthog/test/repo_invariants/test_no_sleep_in_test_bodies.py for the replacement:\n" + "\n".join(offenders)
    )
