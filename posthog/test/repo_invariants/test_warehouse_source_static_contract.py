"""Ratchets on warehouse source code that can hold a worker with no way to stop it.

A worker that shuts down hands each running import to another worker, but only when the source
gives control back to the pipeline. Three patterns in source code prevent that, and each one has a
baseline here that may only get shorter:

- a raw `time.sleep`, which no shutdown can interrupt and which nothing caps;
- an HTTP call on a session with no `timeout=`, which waits without limit for a stalled server;
- a generator that wraps a REST framework resource and reaches no safe point, which turns the
  framework safe points off, so a run of empty pages gives the pipeline nothing to act on.

The behavior tests in `products/warehouse_sources/.../sources/tests/test_source_contract.py` cover
the sources that a fake HTTP server can drive. These checks cover every source, also the ones that
use a driver or an SDK.
"""

import ast
import sys
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
BASELINE_DIR = Path(__file__).parent
SOURCES_ROOT = REPO_ROOT / "products/warehouse_sources/backend/temporal/data_imports/sources"
SKIPPED_DIRS = {"common", "tests", "test", "__pycache__", "generated_configs"}
REGENERATE = "python posthog/test/repo_invariants/test_warehouse_source_static_contract.py"

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "request", "send"}
HTTP_MODULES = {"requests", "httpx"}
RESOURCE_BUILDERS = {"rest_api_resource", "rest_api_resources", "build_dependent_resource", "build_chained_resource"}
SAFE_POINT_CALLS = {"safe_point", "reach_safe_point"}

Check = Callable[[ast.Module], list[str]]


def _own_nodes(node: ast.AST) -> list[ast.AST]:
    """The nodes of a function or module, without the bodies of functions defined inside it."""
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        nodes.append(current)
        if not isinstance(current, FUNCTIONS):
            stack.extend(ast.iter_child_nodes(current))
    return nodes


def _scopes(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    """Each function of the module with its qualified name, plus the module body as `<module>`."""
    scopes: list[tuple[str, ast.AST]] = [("<module>", tree)]

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualified = f"{prefix}{child.name}"
                scopes.append((qualified, child))
                visit(child, f"{qualified}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return scopes


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _called_name(node: ast.AST | None) -> str | None:
    return _terminal_name(node.func) if isinstance(node, ast.Call) else None


def raw_sleeps(tree: ast.Module) -> list[str]:
    sleep_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "time"
        for alias in node.names
        if alias.name == "sleep"
    }

    def is_sleep(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return func.id in sleep_names
        return (
            isinstance(func, ast.Attribute)
            and func.attr == "sleep"
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        )

    return [name for name, scope in _scopes(tree) if any(is_sleep(node) for node in _own_nodes(scope))]


def _is_session_annotation(annotation: ast.AST) -> bool:
    """A `Session` annotation, also as `Session | None`. Not `dict[str, Callable[[Session], ...]]`."""
    if isinstance(annotation, ast.BinOp):
        return _is_session_annotation(annotation.left) or _is_session_annotation(annotation.right)
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return "Session" in annotation.value and "[" not in annotation.value
    return "Session" in (_terminal_name(annotation) or "")


def requests_without_timeout(tree: ast.Module) -> list[str]:
    # A name is a session when `make_tracked_session` builds it, or when its annotation says so.
    sessions: set[str | None] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _called_name(node.value) == "make_tracked_session":
            sessions.update(_terminal_name(target) for target in node.targets)
        elif isinstance(node, ast.AnnAssign) and (
            _called_name(node.value) == "make_tracked_session" or _is_session_annotation(node.annotation)
        ):
            sessions.add(_terminal_name(node.target))
        elif isinstance(node, ast.arg) and node.annotation is not None and _is_session_annotation(node.annotation):
            sessions.add(node.arg)

    def is_unbounded_request(node: ast.AST) -> bool:
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in HTTP_VERBS):
            return False
        receiver = _terminal_name(node.func.value)
        if receiver is None:
            return False
        is_http_module = isinstance(node.func.value, ast.Name) and receiver in HTTP_MODULES
        if not (is_http_module or receiver in sessions or "session" in receiver.lower()):
            return False
        # A `**kwargs` argument can carry the timeout.
        return not any(keyword.arg in ("timeout", None) for keyword in node.keywords)

    return [name for name, scope in _scopes(tree) if any(is_unbounded_request(node) for node in _own_nodes(scope))]


def wrapped_resources_without_safe_point(tree: ast.Module) -> list[str]:
    def builds_resource(node: ast.AST | None) -> bool:
        while isinstance(node, ast.Subscript):
            node = node.value
        return _called_name(node) in RESOURCE_BUILDERS

    resource_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign) and builds_resource(node.value):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                resource_names.update(leaf.id for leaf in ast.walk(target) if isinstance(leaf, ast.Name))

    def is_resource(node: ast.AST | None) -> bool:
        # `iter(resource)` and `enumerate(resource)` still read the resource.
        while isinstance(node, ast.Call) and _called_name(node) in ("iter", "enumerate") and node.args:
            node = node.args[0]
        return builds_resource(node) or (isinstance(node, ast.Name) and node.id in resource_names)

    found: list[str] = []
    for name, scope in _scopes(tree):
        if isinstance(scope, ast.Module):
            continue
        nodes = _own_nodes(scope)
        if not any(isinstance(node, ast.Yield | ast.YieldFrom) for node in nodes):
            continue
        reads_resource = any(
            (isinstance(node, ast.YieldFrom) and is_resource(node.value))
            or (isinstance(node, ast.For | ast.comprehension) and is_resource(node.iter))
            for node in nodes
        )
        if reads_resource and not any(_called_name(node) in SAFE_POINT_CALLS for node in nodes):
            found.append(name)
    return found


# Each check: the collector, the words of which a file must hold one to be parsed, the baseline file,
# and what a '+' line means.
CHECKS: dict[str, tuple[Check, tuple[str, ...], str, str]] = {
    "raw_sleep": (
        raw_sleeps,
        ("sleep",),
        "source_raw_sleep_baseline.txt",
        "A '+' line is a source function that calls `time.sleep`. A worker shutdown cannot interrupt that wait, "
        "and nothing caps it, so one large `Retry-After` value holds the worker. Let the REST client or the "
        "tracked session own the retry wait. Where the source must wait, cap the wait and reach a safe point "
        "(`ResumableSourceManager.safe_point()`) before it.",
    ),
    "request_without_timeout": (
        requests_without_timeout,
        ("ession", "requests.", "httpx."),
        "source_request_without_timeout_baseline.txt",
        "A '+' line is a source function that sends an HTTP request on a session with no `timeout=` argument. "
        "A server that accepts the connection and then sends nothing holds the worker without limit. "
        "Pass `timeout=(connect_seconds, read_seconds)` at the call.",
    ),
    "wrapped_resource": (
        wrapped_resources_without_safe_point,
        tuple(RESOURCE_BUILDERS),
        "source_wrapped_resource_baseline.txt",
        "A '+' line is a generator that reads a REST framework resource and yields its pages again. The "
        "framework reaches a safe point after each page only when the pipeline reads the resource directly, "
        "so behind a wrapper a run of empty pages never lets the pipeline stop the run. Return the resource "
        "itself as `SourceResponse.items`, or call `ResumableSourceManager.safe_point()` in the wrapper after "
        "each page that the wrapper has handed on in full.",
    ),
}


def collect(check: Check, words: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in SOURCES_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCES_ROOT)
        if SKIPPED_DIRS.intersection(relative.parts) or path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if not any(word in source for word in words):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source)
        except SyntaxError:
            continue
        found.extend(f"{relative.as_posix()}::{name}" for name in check(tree))
    return sorted(set(found))


# A baseline test cannot catch a detection regression on its own: a function that stops being
# detected leaves as a '-' line, which reads as a function someone fixed.
DETECTION_CASES = [
    ("raw_sleep", "import time\ndef rows():\n    time.sleep(5)\n", ["rows"]),
    ("raw_sleep", "from time import sleep as pause\ndef rows():\n    pause(5)\n", ["rows"]),
    ("raw_sleep", "import time\ntime.sleep(1)\n", ["<module>"]),
    ("raw_sleep", "import time\nclass Client:\n    def get(self):\n        time.sleep(1)\n", ["Client.get"]),
    (
        "raw_sleep",
        "import time\ndef rows():\n    def wait():\n        time.sleep(1)\n    wait()\n",
        ["rows.wait"],
    ),
    ("raw_sleep", "import asyncio\ndef rows(manager):\n    manager.sleep(5)\n    started = time.monotonic()\n", []),
    ("request_without_timeout", "def rows(session):\n    return session.get(url)\n", ["rows"]),
    ("request_without_timeout", "def rows(session):\n    return session.get(url, timeout=30)\n", []),
    ("request_without_timeout", "def rows(self):\n    return self._session.post(url, json=body)\n", ["rows"]),
    ("request_without_timeout", "def rows(session, **kwargs):\n    return session.request('GET', url, **kwargs)\n", []),
    (
        "request_without_timeout",
        "def rows():\n    http = make_tracked_session()\n    return http.get(url)\n",
        ["rows"],
    ),
    ("request_without_timeout", "def rows(http: requests.Session):\n    return http.get(url)\n", ["rows"]),
    ("request_without_timeout", "import requests\ndef rows():\n    return requests.get(url)\n", ["rows"]),
    ("request_without_timeout", "def rows(cache):\n    return cache.get(key)\n", []),
    (
        "request_without_timeout",
        "import requests\nrows: dict[str, Callable[[requests.Session], list]] = {}\ndef pick(name):\n    return rows.get(name)\n",
        [],
    ),
    ("request_without_timeout", "def rows(http: requests.Session | None):\n    return http.get(url)\n", ["rows"]),
    (
        "wrapped_resource",
        "def rows(config):\n    resource = rest_api_resource(config)\n    for page in resource:\n        yield page\n",
        ["rows"],
    ),
    ("wrapped_resource", "def rows(config):\n    yield from rest_api_resources(config)[0]\n", ["rows"]),
    (
        "wrapped_resource",
        "def source(config):\n"
        "    resource = build_dependent_resource(config)\n"
        "    def items():\n"
        "        yield from iter(resource)\n"
        "    return items\n",
        ["source.items"],
    ),
    (
        "wrapped_resource",
        "def rows(config, manager):\n"
        "    for page in rest_api_resource(config):\n"
        "        yield page\n"
        "        manager.safe_point()\n",
        [],
    ),
    ("wrapped_resource", "def source(config):\n    return rest_api_resource(config)\n", []),
    ("wrapped_resource", "def rows(pages):\n    for page in pages:\n        yield page\n", []),
]


@pytest.mark.parametrize(("check", "source", "expected"), DETECTION_CASES)
def test_detection(check: str, source: str, expected: list[str]) -> None:
    assert CHECKS[check][0](ast.parse(source)) == expected


def read_baseline(file_name: str) -> list[str]:
    return sorted(line for line in (BASELINE_DIR / file_name).read_text().splitlines() if line.strip())


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_source_functions_match_the_baseline(check: str) -> None:
    collector, words, file_name, explanation = CHECKS[check]
    scanned = collect(collector, words)
    recorded = read_baseline(file_name)
    if scanned == recorded:
        return

    added = [line for line in scanned if line not in recorded]
    removed = [line for line in recorded if line not in scanned]
    report = "\n".join([*(f"  + {line}" for line in added), *(f"  - {line}" for line in removed)])
    raise AssertionError(
        f"{file_name} no longer matches the repo.\n"
        f"{explanation} Do not add the line to the baseline: the list may only get shorter.\n"
        f"A '-' line means a function was fixed. The file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )


if __name__ == "__main__":
    for collector, words, file_name, _explanation in CHECKS.values():
        functions = collect(collector, words)
        (BASELINE_DIR / file_name).write_text("\n".join(functions) + "\n")
        sys.stdout.write(f"{file_name} written: {len(functions)} functions\n")
