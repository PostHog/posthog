import ast
import subprocess
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE = Path(__file__).with_name("test_sleep_baseline.txt")
_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _resolve_name(node: ast.AST | None, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, "")
    if isinstance(node, ast.Attribute):
        return f"{_resolve_name(node.value, aliases)}.{node.attr}"
    return ""


def _own_scope_nodes(node: ast.AST) -> Iterator[ast.AST]:
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, _SCOPES):
            yield from _own_scope_nodes(child)


def _scope_aliases(node: ast.AST, enclosing_aliases: dict[str, str]) -> dict[str, str]:
    aliases = enclosing_aliases.copy()
    nodes = list(_own_scope_nodes(node))
    for child in nodes:
        if isinstance(child, ast.Import):
            aliases.update({alias.asname or alias.name: alias.name for alias in child.names})
        elif isinstance(child, ast.ImportFrom):
            module = "." * child.level + (child.module or "")
            aliases.update({alias.asname or alias.name: f"{module}.{alias.name}" for alias in child.names})
    for child in nodes:
        if isinstance(child, ast.Assign) and _resolve_name(child.value, aliases) == "time.sleep":
            aliases.update({target.id: "time.sleep" for target in child.targets if isinstance(target, ast.Name)})
        elif (
            isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and _resolve_name(child.value, aliases) == "time.sleep"
        ):
            aliases[child.target.id] = "time.sleep"
    return aliases


def _definition_expressions(node: ast.AST) -> Iterator[ast.AST]:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        yield node.args
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        yield from node.decorator_list
        if node.returns is not None:
            yield node.returns
    elif isinstance(node, ast.ClassDef):
        yield from node.decorator_list
        yield from node.bases
        yield from node.keywords


def sleep_calls(source: str, *, filename: str = "<unknown>") -> Counter[str]:
    tree = ast.parse(source, filename=filename)
    calls: Counter[str] = Counter()

    def visit(
        node: ast.AST, scope: tuple[str, ...], aliases: dict[str, str], enclosing_aliases: dict[str, str]
    ) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            scope = (*scope, node.name)
        for expression in _definition_expressions(node):
            visit(expression, scope, aliases, enclosing_aliases)
        if isinstance(node, _SCOPES):
            aliases = _scope_aliases(node, enclosing_aliases)
            # Class bodies do not provide the enclosing bindings for their methods.
            if not isinstance(node, ast.ClassDef):
                enclosing_aliases = aliases
        if isinstance(node, ast.Call) and _resolve_name(node.func, aliases) == "time.sleep":
            call = ast.Call(func=ast.Name(id="sleep", ctx=ast.Load()), args=node.args, keywords=node.keywords)
            calls[f"{'.'.join(scope) or '<module>'}::{ast.unparse(call)}"] += 1
        children: Iterable[ast.AST]
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            children = node.body
        elif isinstance(node, ast.Lambda):
            children = [node.body]
        else:
            children = ast.iter_child_nodes(node)
        for child in children:
            visit(child, scope, aliases, enclosing_aliases)

    visit(tree, (), {}, {})
    return calls


def is_test_file(path: Path) -> bool:
    return (
        path.name == "conftest.py"
        or path.match("test_*.py")
        or path.match("*_test.py")
        or bool({"test", "tests"}.intersection(path.parts))
    )


def collect_sleeps() -> Counter[str]:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=REPO_ROOT,
        text=True,
    ).split("\0")
    found: Counter[str] = Counter()
    for name in paths:
        path = REPO_ROOT / name
        if not name or not is_test_file(Path(name)) or not path.is_file():
            continue
        source = path.read_text()
        if "sleep" not in source:
            continue
        for call, count in sleep_calls(source, filename=name).items():
            found[f"{name}::{call}"] = count
    return found


def test_no_new_test_sleeps() -> None:
    recorded = Counter(
        {call: int(count) for count, call in (line.split(" ", 1) for line in BASELINE.read_text().splitlines())}
    )
    found = collect_sleeps()
    added = list((found - recorded).elements())
    removed = list((recorded - found).elements())
    assert not added and not removed, (
        "Test sleep calls changed. Wait for an event or condition, control the clock, or set timestamps explicitly.\n"
        "Inline noqa comments do not exempt calls. The baseline records existing calls, not whole files or functions.\n"
        "Remove stale baseline entries when deleting a sleep. New exceptions require review of the baseline change.\n"
        + "\n".join([*(f"+ {call}" for call in added), *(f"- {call}" for call in removed)])
    )


@pytest.mark.parametrize(
    "source, expected",
    [
        ("import time\ndef test_wait():\n    time.sleep(1) # noqa: TID251\n", {"test_wait::sleep(1)": 1}),
        ("# ruff: noqa\nimport time as clock\ndef test_wait():\n    clock.sleep(1)\n", {"test_wait::sleep(1)": 1}),
        ("from time import sleep as pause\ndef test_wait():\n    pause(1)\n", {"test_wait::sleep(1)": 1}),
        ("import time\npause = time.sleep\ndef test_wait():\n    pause(1)\n", {"test_wait::sleep(1)": 1}),
        ("import time\ndef test_wait():\n    time.sleep(1)\n    time.sleep(1)\n", {"test_wait::sleep(1)": 2}),
        (
            "import time\nclass TestWait:\n    def test_wait(self):\n        time.sleep(2)\n",
            {"TestWait.test_wait::sleep(2)": 1},
        ),
        ("import time\nreal_sleep = time.sleep\n", {}),
        ("from elsewhere import sleep\ndef test_wait():\n    sleep(1)\n", {}),
        ("from .time import sleep\ndef test_wait():\n    sleep(1)\n", {}),
        (
            "import time\ndef test_wait():\n    time.sleep(1)\n"
            "def test_timestamp():\n    from time import time\n    return time()\n",
            {"test_wait::sleep(1)": 1},
        ),
        (
            "from time import sleep\nasync def test_wait():\n    from asyncio import sleep\n    await sleep(0)\n",
            {},
        ),
        (
            "import time\nfrom collections.abc import Callable\npause: Callable[[float], None] = time.sleep\n"
            "def test_wait():\n    pause(1)\n",
            {"test_wait::sleep(1)": 1},
        ),
        (
            "import time\nclass TestWait:\n    from datetime import time\n"
            "    def test_wait(self):\n        time.sleep(1)\n",
            {"TestWait.test_wait::sleep(1)": 1},
        ),
        (
            "class TestWait:\n    import time\n    def test_wait(self):\n        time.sleep(1)\n",
            {},
        ),
        (
            "import time\ndef test_wait(value=time.sleep(1)):\n    from datetime import time\n",
            {"test_wait::sleep(1)": 1},
        ),
        (
            "class TestWait:\n    from time import sleep\n    def test_wait(self, value=sleep(1)):\n        pass\n",
            {"TestWait.test_wait::sleep(1)": 1},
        ),
    ],
)
def test_sleep_detection(source: str, expected: dict[str, int]) -> None:
    assert sleep_calls(source) == expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ("posthog/api/test/test_cohort.py", True),
        ("tools/new_tool/check_test.py", True),
        ("services/new_service/tests/helper.py", True),
        ("products/new_product/conftest.py", True),
        ("posthog/production.py", False),
    ],
)
def test_sleep_scan_scope(path: str, expected: bool) -> None:
    assert is_test_file(Path(path)) is expected


def test_an_existing_exception_does_not_allow_another_sleep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    test_file = tmp_path / "test_calls.py"
    source = "import time\ndef test_poll():\n    time.sleep(0.1)\n"
    test_file.write_text(source)
    subprocess.run(["git", "-C", str(tmp_path), "add", test_file.name], check=True)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("1 test_calls.py::test_poll::sleep(0.1)\n")
    monkeypatch.setattr(f"{__name__}.REPO_ROOT", tmp_path)
    monkeypatch.setattr(f"{__name__}.BASELINE", baseline)

    test_no_new_test_sleeps()

    test_file.write_text(source + "    time.sleep(0.1)  # noqa: TID251\n")
    with pytest.raises(AssertionError, match="Test sleep calls changed"):
        test_no_new_test_sleeps()


if __name__ == "__main__":
    test_no_new_test_sleeps()
