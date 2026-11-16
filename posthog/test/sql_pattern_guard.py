import re
import traceback
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from django.db import connections

from posthog.dataclasses import frozen

PatternKind = Literal["correlated", "cross-table", "same-row", "unknown"]

# Postgres evaluates a pattern from another row once per outer row, while a same-row pattern only filters each row.
FAILING_KINDS: frozenset[PatternKind] = frozenset({"correlated", "cross-table"})

_OPERATOR_NEEDLES = ("LIKE", "like", "SIMILAR TO", "similar to", "~")
_OPERATOR_TAIL = re.compile(r"\*?\s+")
_CONSTANT_START = re.compile(r"(?:%s|'|E'|\$\d|%\(\w+\)s)")
# Function wrappers and `'..' ||` prefixes that still leave a constant pattern when their argument is a parameter.
_WRAPPER = re.compile(r"(?:(?:UPPER|LOWER|ANY|ALL)\s*\(\s*|'(?:[^']|'')*'\s*\|\|\s*|\(\s*)", re.IGNORECASE)
_OPERAND_END = re.compile(
    r"\s+(?:AND|OR|THEN|ELSE|END|WHEN|ESCAPE|ORDER|GROUP|LIMIT|HAVING|UNION)\b|[),]|$", re.IGNORECASE
)
_NON_COLUMN_TOKENS = re.compile(
    r"'(?:[^']|'')*'|%s|%\(\w+\)s|\$\d+|::\s*\w+|\b[A-Za-z_]\w*\s*\(|\b(?:E|TEXT|VARCHAR|NULL)\b|\d+", re.IGNORECASE
)
_IDENTIFIER = re.compile(r'"?[A-Za-z_][\w$]*"?')
_QUALIFIED_REF = re.compile(r'("?[A-Za-z_][\w$]*"?)\s*\.\s*"?[A-Za-z_][\w$]*"?')
_SUBQUERY_START = re.compile(r"\(\s*SELECT\b", re.IGNORECASE)
_FROM_ALIAS = re.compile(
    r'\b(?:FROM|JOIN)\s+(?:LATERAL\s+)?("?[A-Za-z_][\w$.]*"?(?:\."?[A-Za-z_][\w$]*"?)?)'
    r"(?:\s+(?:AS\s+)?(?!(?:WHERE|INNER|LEFT|RIGHT|FULL|CROSS|JOIN|ON|GROUP|ORDER|LIMIT|USING|NATURAL|WINDOW|HAVING|UNION|FOR)\b)"
    r'("?[A-Za-z_][\w$]*"?))?',
    re.IGNORECASE,
)

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[2]


@frozen
class ColumnPattern:
    kind: PatternKind
    operand: str
    position: int


class OuterRowPatternError(AssertionError):
    pass


def find_column_patterns(sql: str) -> list[ColumnPattern]:
    if "LIKE" not in sql and "~" not in sql and "like" not in sql and "SIMILAR" not in sql and "similar" not in sql:
        return []
    return [
        ColumnPattern(kind=_classify(sql, position, operand), operand=operand.strip(), position=position)
        for position, operand in _column_pattern_operands(sql)
    ]


def _operator_spans(sql: str) -> Iterator[tuple[int, int]]:
    for needle in _OPERATOR_NEEDLES:
        start = sql.find(needle)
        while start != -1:
            after = start + len(needle)
            before = sql[start - 1] if start else " "
            if needle == "~":
                tail = _OPERATOR_TAIL.match(sql, after)
                if tail and (before.isspace() or before == "!"):
                    yield start, tail.end()
            # The `Ii` exception keeps ILIKE, which the `LIKE` needle matches one character in.
            elif after < len(sql) and sql[after].isspace() and not (before.isalnum() and before not in "Ii"):
                yield start, after + 1
            start = sql.find(needle, after)


def _column_pattern_operands(sql: str) -> list[tuple[int, str]]:
    operands: list[tuple[int, str]] = []
    for op_start, op_end in _operator_spans(sql):
        pos = op_end
        while pos < len(sql) and sql[pos].isspace():
            pos += 1
        while (wrapper := _WRAPPER.match(sql, pos)) is not None and wrapper.end() != pos:
            pos = wrapper.end()
        if _CONSTANT_START.match(sql, pos):
            continue
        end = _OPERAND_END.search(sql, pos)
        operand = sql[pos : end.start() if end else len(sql)]
        if _IDENTIFIER.search(_NON_COLUMN_TOKENS.sub(" ", operand)):
            operands.append((op_start, operand))
    return operands


def _matching_paren(sql: str, open_pos: int) -> int:
    depth = 0
    for i in range(open_pos, len(sql)):
        if sql[i] == "(":
            depth += 1
        elif sql[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return len(sql)


def _enclosing_select(sql: str, pos: int) -> tuple[int, int] | None:
    depth = 0
    for i in range(pos - 1, -1, -1):
        if sql[i] == ")":
            depth += 1
        elif sql[i] == "(":
            if depth:
                depth -= 1
            elif _SUBQUERY_START.match(sql, i):
                return i, _matching_paren(sql, i)
    return None


def _top_level(segment: str) -> str:
    out: list[str] = []
    depth = 0
    for char in segment:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif depth == 0:
            out.append(char)
    return "".join(out)


def _scope_aliases(scope_sql: str) -> set[str]:
    return {
        (alias or table.split(".")[-1]).strip('"').lower()
        for table, alias in _FROM_ALIAS.findall(_top_level(scope_sql))
    }


def _qualified_refs(sql: str) -> list[str]:
    return [ref.strip('"').lower() for ref in _QUALIFIED_REF.findall(sql)]


def _classify(sql: str, op_pos: int, operand: str) -> PatternKind:
    # Django aliases the tables of a subquery U0, U1, and so on, while an OuterRef keeps the outer table's name. So an
    # operand inside a subquery that names a table its own FROM clause does not define reads the outer row.
    refs = set(_qualified_refs(operand))
    if not refs:
        return "unknown"
    enclosing = _enclosing_select(sql, op_pos)
    if enclosing is not None:
        inner = _scope_aliases(sql[enclosing[0] + 1 : enclosing[1]])
        return "correlated" if refs - inner else "same-row"
    lhs = set(_qualified_refs(sql[max(0, op_pos - 120) : op_pos])[-1:])
    if lhs and refs - lhs:
        return "cross-table"
    return "same-row"


def _emitting_frames() -> tuple[str, str]:
    app_frame = test_frame = ""
    for frame in reversed(traceback.extract_stack()):
        path = Path(frame.filename)
        if path == _THIS_FILE or not path.is_relative_to(_REPO_ROOT):
            continue
        relative = path.relative_to(_REPO_ROOT)
        if relative.parts[0].startswith(".") or "site-packages" in relative.parts:
            continue
        location = f"{relative}:{frame.lineno}"
        if "test" in relative.parts or relative.name.startswith("test_") or relative.name == "conftest.py":
            test_frame = test_frame or location
        else:
            app_frame = app_frame or location
        if app_frame and test_frame:
            break
    return app_frame, test_frame


def _excerpt(sql: str, position: int) -> str:
    start = max(0, position - 300)
    end = min(len(sql), position + 300)
    return f"{'...' if start else ''}{sql[start:end]}{'...' if end < len(sql) else ''}"


def _describe(sql: str, pattern: ColumnPattern) -> str:
    source = " via ".join(frame for frame in _emitting_frames() if frame) or "unknown"
    reads = "a column of the outer query" if pattern.kind == "correlated" else "a column of another joined table"
    return (
        f"  kind:    {pattern.kind} (the pattern reads {reads})\n"
        f"  operand: {pattern.operand[:200]}\n"
        f"  emitted: {source}\n"
        f"  sql:     {_excerpt(sql, pattern.position)}"
    )


def _failure_message(failures: list[str]) -> str:
    return (
        "A query builds a LIKE, regex or SIMILAR TO pattern from a column of another row. Postgres cannot use an "
        "index for it, so it evaluates the pattern once per outer row and the query slows down as the table grows.\n\n"
        + "\n\n".join(failures)
        + "\n\nFix: match constant prefixes, as `_visible_files` in posthog/api/file_system/file_system.py does, "
        "or join on an exact column value.\n"
        'Reviewed exception: run the query inside `with allow_outer_row_pattern(reason="..."):` '
        "from posthog.test.sql_pattern_guard."
    )


_innermost_guard: ContextVar[list[str] | None] = ContextVar("_innermost_guard", default=None)
_allowed_reason: ContextVar[str | None] = ContextVar("_allowed_reason", default=None)


@contextmanager
def allow_outer_row_pattern(reason: str) -> Iterator[None]:
    if not reason.strip():
        raise ValueError("allow_outer_row_pattern needs a reason a reviewer can check")
    token = _allowed_reason.set(reason)
    try:
        yield
    finally:
        _allowed_reason.reset(token)


@contextmanager
def fail_on_outer_row_patterns() -> Iterator[None]:
    failures: list[str] = []

    def record(execute: Callable[..., Any], sql: Any, params: Any, many: bool, context: dict[str, Any]) -> Any:
        # Only the innermost guard records, so a nested guard's query does not also fail the outer guard.
        if isinstance(sql, str) and _innermost_guard.get() is failures and _allowed_reason.get() is None:
            failures.extend(_describe(sql, p) for p in find_column_patterns(sql) if p.kind in FAILING_KINDS)
        return execute(sql, params, many, context)

    token = _innermost_guard.set(failures)
    try:
        with ExitStack() as stack:
            for alias in connections:
                stack.enter_context(connections[alias].execute_wrapper(record))
            yield
    finally:
        _innermost_guard.reset(token)
    if failures:
        raise OuterRowPatternError(_failure_message(failures))
