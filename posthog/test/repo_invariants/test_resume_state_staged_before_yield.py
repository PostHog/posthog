"""Ratchet on warehouse sources that save resumable state after the `yield` it covers.

The pipeline commits staged state right after it writes a batch, and on a worker shutdown it ends
the attempt before control returns to the source. State saved after a `yield` is therefore lost for
the last batch: the next attempt reads that batch again, and an attempt that writes one batch or
fewer keeps no progress at all. The failure message says how to fix a reported function.
"""

import ast
import warnings
from pathlib import Path

from parameterized import parameterized

REPO_ROOT = Path(__file__).parents[3]
BASELINE_PATH = Path(__file__).parent / "resume_state_after_yield_baseline.txt"
SOURCES_ROOT = REPO_ROOT / "products/warehouse_sources/backend/temporal/data_imports/sources"
SKIPPED_DIRS = {"tests", "test", "__pycache__"}
REGENERATE = "python posthog/test/repo_invariants/test_resume_state_staged_before_yield.py"

FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(statement: ast.stmt) -> list[ast.AST]:
    """The nodes of a statement, without the bodies of functions defined inside it.

    A resume hook defined in a loop body runs when the framework calls it, not where it is written.
    """
    nodes: list[ast.AST] = []
    stack: list[ast.AST] = [statement]
    while stack:
        node = stack.pop()
        nodes.append(node)
        stack.extend(child for child in ast.iter_child_nodes(node) if not isinstance(child, FUNCTIONS))
    return nodes


def _yields(statement: ast.stmt) -> bool:
    return any(isinstance(node, ast.Yield | ast.YieldFrom) for node in _own_nodes(statement))


def _is_save_call(node: ast.AST, callbacks: frozenset[str] = frozenset()) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute):
        return node.func.attr == "save_state"
    return isinstance(node.func, ast.Name) and node.func.id in callbacks


def _saves_state(statement: ast.stmt, callbacks: frozenset[str] = frozenset()) -> bool:
    return any(_is_save_call(node, callbacks) for node in _own_nodes(statement))


def _saving_helpers(tree: ast.Module) -> frozenset[str]:
    """Functions that call `save_state` and yield nothing. A call to one of them stages state."""
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and any(_saves_state(statement) for statement in node.body)
        and not any(_yields(statement) for statement in node.body)
    )


def _callback_parameters(tree: ast.Module) -> frozenset[str]:
    """Keyword names that receive a saving helper, as in `checkpoint=_checkpoint`.

    A generator that takes such a parameter and calls it stages state in a function the generator
    does not define.
    """
    helpers = _saving_helpers(tree)
    return frozenset(
        keyword.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg is not None and isinstance(keyword.value, ast.Name) and keyword.value.id in helpers
    )


def _loop_blocks(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[list[ast.stmt]]:
    """Every statement block that runs once per loop iteration.

    A save after the last `yield` of the whole walk is left alone: the generator ends right after
    it, and the pipeline then commits the state with the rows it still holds.
    """
    blocks: list[list[ast.stmt]] = []
    stack: list[tuple[ast.AST, bool]] = [(function, False)]
    while stack:
        node, in_loop = stack.pop()
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not (isinstance(block, list) and block and isinstance(block[0], ast.stmt)):
                continue
            block_in_loop = in_loop or (field == "body" and isinstance(node, ast.For | ast.AsyncFor | ast.While))
            if block_in_loop:
                blocks.append(block)
            stack.extend((statement, block_in_loop) for statement in block if not isinstance(statement, FUNCTIONS))
        for field in ("handlers", "cases"):
            stack.extend((child, in_loop) for child in getattr(node, field, None) or [])
    return blocks


def _saves_after_yield(
    function: ast.FunctionDef | ast.AsyncFunctionDef, callbacks: frozenset[str] = frozenset()
) -> bool:
    """Whether a loop of the function saves state after the last `yield` of an iteration.

    A save that another `yield` follows in the same block is state for that later batch, staged
    before it, which is the wanted order.
    """
    for block in _loop_blocks(function):
        yielded = False
        save_is_last = False
        for statement in block:
            if isinstance(statement, FUNCTIONS):
                continue
            if _yields(statement):
                # A compound statement that holds both is judged by its own blocks.
                yielded = True
                save_is_last = False
            elif yielded and _saves_state(statement, callbacks):
                save_is_last = True
        if save_is_last:
            return True
    return False


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    arguments = function.args
    return frozenset(argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs))


def _functions_in_tree(tree: ast.Module, callback_parameters: frozenset[str]) -> list[str]:
    helpers = _saving_helpers(tree)
    names: list[str] = []

    def visit(node: ast.AST, prefix: str, parameters: frozenset[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                qualified = f"{prefix}{child.name}"
                # A callback counts only where it is a parameter of the function, or of one around it.
                in_scope = parameters | _parameters(child)
                if _saves_after_yield(child, helpers | (callback_parameters & in_scope)):
                    names.append(qualified)
                visit(child, f"{qualified}.", in_scope)
            elif isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.", parameters)
            else:
                visit(child, prefix, parameters)

    visit(tree, "", frozenset())
    return names


def _functions_in_source(source: str) -> list[str]:
    tree = ast.parse(source)
    return _functions_in_tree(tree, _callback_parameters(tree))


def _parse(source: str) -> ast.Module | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(source)
    except SyntaxError:
        return None


def collect_functions() -> list[str]:
    sources: dict[str, str] = {}
    for file in SOURCES_ROOT.rglob("*.py"):
        relative = file.relative_to(SOURCES_ROOT)
        if SKIPPED_DIRS.intersection(relative.parts) or file.name.startswith("test_"):
            continue
        source = file.read_text(encoding="utf-8", errors="ignore")
        if "yield" in source or "save_state" in source:
            sources[relative.as_posix()] = source

    trees = {path: tree for path, source in sources.items() if "save_state" in source and (tree := _parse(source))}
    # Shared code takes the callback as a parameter, and a source module passes it in. The keyword
    # names from every module therefore apply to every module.
    callback_parameters = frozenset[str]().union(*(_callback_parameters(tree) for tree in trees.values()))
    for path, source in sources.items():
        if path not in trees and any(name in source for name in callback_parameters) and (tree := _parse(source)):
            trees[path] = tree

    found: list[str] = []
    for path, tree in trees.items():
        found.extend(f"{path}::{name}" for name in _functions_in_tree(tree, callback_parameters))
    return sorted(set(found))


# The baseline test cannot catch a detection regression on its own: a function that stops being
# detected leaves as a '-' line, which reads as a function someone fixed.
DETECTION_CASES = [
    (
        "save_after_the_yield_is_reported",
        "def rows(manager):\n    for page in pages():\n        yield page\n        manager.save_state(page.cursor)\n",
        ["rows"],
    ),
    (
        "save_before_the_yield_is_the_wanted_order",
        "def rows(manager):\n    for page in pages():\n        manager.save_state(page.cursor)\n        yield page\n",
        [],
    ),
    (
        "conditional_save_after_the_yield_is_reported",
        "def rows(manager):\n"
        "    for page in pages():\n"
        "        if page.rows:\n"
        "            yield page.rows\n"
        "        if page.cursor:\n"
        "            manager.save_state(page.cursor)\n",
        ["rows"],
    ),
    (
        "save_after_a_delegated_generator_is_reported",
        "def rows(manager):\n"
        "    for window in windows():\n"
        "        yield from read(window)\n"
        "        manager.save_state(window.end)\n",
        ["rows"],
    ),
    (
        "save_between_two_yields_belongs_to_the_second",
        "def rows(manager):\n"
        "    for page in pages():\n"
        "        yield page.header\n"
        "        manager.save_state(page.cursor)\n"
        "        yield page.rows\n",
        [],
    ),
    (
        "save_after_the_whole_walk_is_left_alone",
        "def rows(manager):\n    for page in pages():\n        yield page\n    manager.save_state(finished())\n",
        [],
    ),
    (
        "save_after_the_yield_inside_a_try_in_a_loop_is_reported",
        "def rows(manager):\n"
        "    while True:\n"
        "        try:\n"
        "            yield fetch()\n"
        "            manager.save_state(cursor())\n"
        "        except StopIteration:\n"
        "            break\n",
        ["rows"],
    ),
    (
        "hook_defined_in_the_loop_is_not_a_save_in_the_loop",
        "def rows(manager):\n"
        "    for window in windows():\n"
        "        yield from read(window)\n"
        "        def hook(state):\n"
        "            manager.save_state(state)\n",
        [],
    ),
    (
        "nested_function_is_reported_under_its_qualified_name",
        "def source(manager):\n"
        "    def items():\n"
        "        for page in pages():\n"
        "            yield page\n"
        "            manager.save_state(page.cursor)\n"
        "    return items\n",
        ["source.items"],
    ),
    (
        "save_through_a_local_helper_after_the_yield_is_reported",
        "def rows(manager):\n"
        "    def checkpoint(cursor):\n"
        "        manager.save_state(cursor)\n"
        "    for page in pages():\n"
        "        yield page\n"
        "        checkpoint(page.cursor)\n",
        ["rows"],
    ),
    (
        "save_through_a_callback_parameter_after_the_yield_is_reported",
        "def pages(run_page, checkpoint):\n"
        "    for page in run_page():\n"
        "        yield page\n"
        "        checkpoint(page.key)\n"
        "def rows(manager):\n"
        "    def _checkpoint(key):\n"
        "        manager.save_state(key)\n"
        "    return pages(run_page, checkpoint=_checkpoint)\n",
        ["pages"],
    ),
    (
        "call_to_a_parameter_that_no_saving_helper_feeds_is_left_alone",
        "def pages(run_page, on_page):\n    for page in run_page():\n        yield page\n        on_page(page.key)\n",
        [],
    ),
    (
        "save_in_a_function_that_yields_nothing_is_left_alone",
        "def checkpoint(manager, cursor):\n    manager.save_state(cursor)\n",
        [],
    ),
]


@parameterized.expand(DETECTION_CASES)
def test_detection(_name: str, source: str, expected: list[str]) -> None:
    assert _functions_in_source(source) == expected


def read_baseline() -> list[str]:
    return sorted(line for line in BASELINE_PATH.read_text().splitlines() if line.strip())


def write_baseline(functions: list[str]) -> None:
    BASELINE_PATH.write_text("\n".join(functions) + "\n")


def test_resume_state_saved_after_a_yield_matches_the_baseline() -> None:
    scanned = collect_functions()
    recorded = read_baseline()
    if scanned == recorded:
        return

    added = [line for line in scanned if line not in recorded]
    removed = [line for line in recorded if line not in scanned]
    report = "\n".join([*(f"  + {line}" for line in added), *(f"  - {line}" for line in removed)])
    raise AssertionError(
        f"{BASELINE_PATH.name} no longer matches the repo.\n"
        "A '+' line is a source generator that calls `save_state` after the `yield` the state covers. "
        "The pipeline commits staged state right after it writes a batch, and on a worker shutdown it "
        "ends the attempt before control returns to the source. That state is lost for the last batch, "
        "so the next attempt reads the batch again, and a full refresh appends it twice. "
        "Call `save_state` before the `yield` of the batch it covers. "
        "Do not add the line to the baseline: the list may only get shorter.\n"
        f"A '-' line means a function was fixed. The file must record that too. Run: {REGENERATE}\n"
        f"{report}"
    )


if __name__ == "__main__":
    functions = collect_functions()
    write_baseline(functions)
    print(f"baseline written: {len(functions)} functions")  # noqa: T201
