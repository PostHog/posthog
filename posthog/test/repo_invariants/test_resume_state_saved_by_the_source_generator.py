"""Warehouse sources must save resumable state from the generator that the pipeline iterates.

The pipeline confirms a saved cursor when the source hands it an item, because the generator is
then suspended and holds no rows that the cursor skips. A coroutine or a thread that reads ahead of
the generator breaks that: it saves a cursor for rows that are still in a queue, the pipeline
commits it, and a later attempt does not read those rows again. The failure message says how to fix
a reported function.
"""

import ast
import warnings
from pathlib import Path

from parameterized import parameterized

REPO_ROOT = Path(__file__).parents[3]
SOURCES_ROOT = REPO_ROOT / "products/warehouse_sources/backend/temporal/data_imports/sources"
SKIPPED_DIRS = {"common", "tests", "test", "__pycache__"}

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
# Calls that run their function argument on another thread or task.
OFF_THREAD_CALLS = {
    "Thread",
    "submit",
    "map",
    "to_thread",
    "run_in_executor",
    "create_task",
    "run_coroutine_threadsafe",
}


def _own_nodes(function: ast.AST) -> list[ast.AST]:
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = [child for child in ast.iter_child_nodes(function) if not isinstance(child, FUNCTIONS)]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, FUNCTIONS))
    return nodes


def _saves_state(function: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "save_state"
        for node in _own_nodes(function)
    )


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    # The builtin `map` runs its function in the calling thread. Only an executor's `map` does not.
    if isinstance(call.func, ast.Name) and call.func.id != "map":
        return call.func.id
    return None


def _off_thread_function_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _called_name(node) in OFF_THREAD_CALLS):
            continue
        for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
            if isinstance(argument, ast.Name):
                names.add(argument.id)
            elif isinstance(argument, ast.Attribute):
                names.add(argument.attr)
    return names


def _functions_in_source(source: str) -> list[str]:
    tree = ast.parse(source)
    off_thread = _off_thread_function_names(tree)
    names: list[str] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualified = f"{prefix}{child.name}"
                runs_off_thread = isinstance(child, ast.AsyncFunctionDef) or child.name in off_thread
                if runs_off_thread and _saves_state(child):
                    names.append(qualified)
                visit(child, f"{qualified}.")
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return names


def collect_functions() -> list[str]:
    found: list[str] = []
    for path in SOURCES_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCES_ROOT)
        if SKIPPED_DIRS.intersection(relative.parts) or path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if "save_state" not in source:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                names = _functions_in_source(source)
        except SyntaxError:
            continue
        found.extend(f"{relative.as_posix()}::{name}" for name in names)
    return sorted(set(found))


DETECTION_CASES = [
    (
        "save_in_a_coroutine_is_reported",
        "async def rows(manager):\n"
        "    async for page in pages():\n"
        "        manager.save_state(page.cursor)\n"
        "        yield page\n",
        ["rows"],
    ),
    (
        "save_in_a_thread_target_is_reported",
        "def source(manager):\n"
        "    def producer():\n"
        "        for page in pages():\n"
        "            manager.save_state(page.cursor)\n"
        "            queue.put(page)\n"
        "    threading.Thread(target=producer, daemon=True).start()\n",
        ["source.producer"],
    ),
    (
        "save_in_a_function_given_to_an_executor_is_reported",
        "def fetch(manager, page):\n"
        "    manager.save_state(page.cursor)\n"
        "def source(manager, executor):\n"
        "    return executor.submit(fetch, manager, first_page())\n",
        ["fetch"],
    ),
    (
        "save_in_the_generator_that_reads_the_queue_is_the_wanted_place",
        "def rows(manager):\n"
        "    def producer():\n"
        "        for page in pages():\n"
        "            queue.put(page)\n"
        "    threading.Thread(target=producer, daemon=True).start()\n"
        "    while True:\n"
        "        page = queue.get()\n"
        "        manager.save_state(page.cursor)\n"
        "        yield page.rows\n",
        [],
    ),
    (
        "hook_defined_in_a_coroutine_is_not_a_save_in_the_coroutine",
        "async def rows(manager):\n    def hook(state):\n        manager.save_state(state)\n    return hook\n",
        [],
    ),
]


@parameterized.expand(DETECTION_CASES)
def test_detection(_name: str, source: str, expected: list[str]) -> None:
    assert _functions_in_source(source) == expected


def test_no_source_saves_resume_state_off_the_generator_thread() -> None:
    found = collect_functions()
    assert found == [], (
        "These functions call `save_state` from a coroutine, or from a function that runs on another "
        "thread or task. Such code reads ahead of the generator that the pipeline iterates, so the "
        "cursor it saves can skip rows that are still in a queue. Pass the resume state through the "
        "queue with the rows, and call `save_state` in the generator when it takes the state from the "
        "queue (see `temporalio/temporalio.py::_async_iter_to_sync`).\n" + "\n".join(f"  {line}" for line in found)
    )
