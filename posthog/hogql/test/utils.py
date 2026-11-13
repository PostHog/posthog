import re
import json
import dataclasses
from collections.abc import Sequence
from typing import Any

from posthog.test.base import clean_varying_query_parts

from pydantic import BaseModel

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.escape_sql import escape_clickhouse_json_path
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.events_json import EVENTS_PROPERTIES_JSON_SUBCOLUMNS, PERSON_PROPERTIES_JSON_SUBCOLUMNS


def execute_hogql_query_with_timings(*args, **kwargs):
    modifiers = kwargs.get("modifiers") or HogQLQueryModifiers()
    modifiers.timings = True
    kwargs["modifiers"] = modifiers
    return execute_hogql_query(*args, **kwargs)


def pretty_print_in_tests(query: str | None, team_id: int) -> str:
    if query is None:
        return ""

    # Newline before each top-level clause keyword for readable snapshots, but skip keywords already at the
    # start of a (possibly indented) line so we don't stack a blank line on top of pretty-printed input. The \b
    # boundaries keep keywords that are substrings of longer tokens intact (e.g. the WHERE inside PREWHERE).
    def _newline_before_clause(match: "re.Match[str]") -> str:
        start = match.start()
        if start > 0 and match.string[start - 1] == "\n":
            return match.group(0)
        whitespace, keyword = match.group(1), match.group(2)
        return f"{whitespace}\n{keyword}"

    query = re.sub(
        r"([ \t]*)\b(SELECT|FROM|PREWHERE|WHERE|GROUP|HAVING|QUALIFY|WINDOW|ORDER|LIMIT|OFFSET|SETTINGS)\b",
        _newline_before_clause,
        query,
    )
    query = query.replace(f"team_id, {team_id})", "team_id, 420)")
    query = re.sub(r"in_cohort__[0-9]+", "in_cohort__XX", query)
    query = re.sub(r"cohort_id, [0-9]+", "cohort_id, XX", query)
    query = re.sub(r"RANDOM_TEST_ID::[a-f0-9\-]+", "RANDOM_TEST_ID::UUID", query)
    return _indent_nested_sql(query)


# A line that opens a clause: the keywords we split on, plus WITH (a clause too, just never split before).
_CLAUSE_LINE = re.compile(
    r"(?:WITH|SELECT|FROM|PREWHERE|WHERE|GROUP|HAVING|QUALIFY|WINDOW|ORDER|LIMIT|OFFSET|SETTINGS)\b"
)


def _indent_nested_sql(query: str) -> str:
    # Indent each already-split line by its bracket-nesting depth so nested subqueries read as nested rather
    # than as one flat sequence, and give continuation lines (a clause body the production printer wrapped
    # onto its own line) one extra level so they sit under their keyword. Naive about brackets inside string
    # literals other than single-quoted ones, which we skip; good enough for test snapshots, no real tokenizer.
    openers, closers = "([{", ")]}"
    depth = 0
    indented_lines: list[str] = []
    for line in query.split("\n"):
        content = line.lstrip(" \t")
        if not content:
            indented_lines.append("")
            continue

        # A line that starts by closing brackets lines up with its opener, so dedent for those leading closers.
        leading_closers = 0
        for char in content:
            if char in closers:
                leading_closers += 1
            else:
                break
        indent = max(depth - leading_closers, 0)
        # Continuation lines — a clause body the printer wrapped onto its own line — nest one deeper than the
        # keyword above them. Lines that open a clause, a comment header, or a bracket (structural, or a data
        # repr passed through this helper) stay at the bracket-depth indent.
        if not (content.startswith("--") or content[0] in openers + closers or _CLAUSE_LINE.match(content)):
            indent += 1
        indented_lines.append("  " * indent + content)

        # Carry the running depth forward by the net brackets on this line, ignoring single-quoted strings.
        opens = shuts = 0
        in_string = escaped = False
        for char in content:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == "'":
                in_string = not in_string
            elif not in_string and char in openers:
                opens += 1
            elif not in_string and char in closers:
                shuts += 1
        depth = max(depth + opens - shuts, 0)

    return "\n".join(indented_lines)


def pretty_print_response_in_tests(response: Any, team_id: int) -> str:
    clickhouse = response.clickhouse
    hogql = response.hogql
    query = "-- ClickHouse\n" + clickhouse + "\n\n-- HogQL\n" + hogql
    return clean_varying_query_parts(pretty_print_in_tests(query, team_id), False)


def pretty_dataclasses(obj, seen=None, indent=0):
    if seen is None:
        seen = set()

    indent_space = " " * indent
    next_indent = " " * (indent + 2)

    if isinstance(obj, BaseModel):
        obj = obj.model_dump()

    if dataclasses.is_dataclass(obj):
        obj_id = id(obj)
        if obj_id in seen:
            return "<recursion ...>"
        seen.add(obj_id)

        field_strings = []
        fields = sorted(dataclasses.fields(obj), key=lambda f: f.name)
        for f in fields:
            value = getattr(obj, f.name)
            if value is not None:
                formatted_value = pretty_dataclasses(value, seen, indent + 2)
                field_strings.append(f"{next_indent}{f.name}: {formatted_value}")

        return "{\n" + "\n".join(field_strings) + "\n" + indent_space + "}"

    elif isinstance(obj, list):
        if len(obj) == 0:
            return "[]"
        elements = [pretty_dataclasses(item, seen, indent + 2) for item in obj]
        return "[\n" + ",\n".join(next_indent + element for element in elements) + "\n" + indent_space + "]"

    elif isinstance(obj, tuple):
        # AST fields typed `list[tuple[...]]` (Dict.items, TryCatchStatement.catches) — render
        # tuple as `(...)` so snapshots distinguish it from list at the same level.
        if len(obj) == 0:
            return "()"
        elements = [pretty_dataclasses(item, seen, indent + 2) for item in obj]
        return "(\n" + ",\n".join(next_indent + element for element in elements) + "\n" + indent_space + ")"

    elif isinstance(obj, dict):
        if len(obj) == 0:
            return "{}"
        sorted_items = sorted(obj.items())
        key_value_pairs = [f"{k}: {pretty_dataclasses(v, seen, indent + 2)}" for k, v in sorted_items]
        return "{\n" + ",\n".join(next_indent + pair for pair in key_value_pairs) + "\n" + indent_space + "}"

    elif isinstance(obj, str):
        return json.dumps(obj)

    elif callable(obj):
        return "<function>"

    else:
        return str(obj)


def native_stored_document(document: str) -> str:
    """A properties document as the native cleaner stores it, for fixtures that cast text into the JSON column.

    Every top-level object and array becomes a string of the JSON text that was sent. Every other value keeps its
    text, so a number token such as `2.0` or `1e21` reaches ClickHouse as it was written.
    """
    decoder = json.JSONDecoder()
    members = []
    index = document.index("{") + 1
    while True:
        index = len(document) - len(document[index:].lstrip())
        if document[index] == "}":
            return "{" + ",".join(members) + "}"
        key, index = decoder.raw_decode(document, index)
        start = len(document) - len(document[document.index(":", index) + 1 :].lstrip())
        _, index = decoder.raw_decode(document, start)
        value = document[start:index]
        members.append(f"{json.dumps(key)}:{json.dumps(value) if value[0] in '[{' else value}")
        index = len(document) - len(document[index:].lstrip())
        if document[index] == ",":
            index += 1


def json_dynamic_read_sql(root: str, path: Sequence[str], *, as_json: bool = False) -> str:
    """The ClickHouse SQL the resolver prints for the read of one property on the native-JSON events table.

    `path` holds the property's key. The read is the text of its path, with the '' that a declared string path stores
    for a missing key read as NULL. `as_json` gives the JSON text of the value instead, where a string that is a
    valid JSON object or array prints unquoted.
    """
    [key] = path
    field = f"{root}.{escape_clickhouse_json_path(key)}"
    declared_types = (
        PERSON_PROPERTIES_JSON_SUBCOLUMNS if root.endswith(".person_properties") else EVENTS_PROPERTIES_JSON_SUBCOLUMNS
    )
    declared_type = declared_types.get(key, "")
    is_declared_string = declared_type in ("String", "LowCardinality(String)")
    if as_json:
        text = f"toString({field})" if is_declared_string else f"CAST({field}, 'Nullable(String)')"
        missing = f"empty({text})" if is_declared_string else f"isNull({field})"
        scalar_json = f"toJSONString({text})" if is_declared_string else f"toJSONString({field})"
        is_container = f"and(in(ascii({text}), tuple(91, 123)), isValidJSON({text}))"
        return f"if({missing}, NULL, if({is_container}, {text}, {scalar_json}))"
    if not is_declared_string:
        return f"CAST({field}, 'Nullable(String)')"
    text = f"nullIf(toString({field}), '')"
    return text if declared_type == "String" else f"CAST({text}, 'Nullable(String)')"
