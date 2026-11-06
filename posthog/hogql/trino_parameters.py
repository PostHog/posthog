import re

from posthog.hogql.errors import ExposedHogQLError

_PYFORMAT_PLACEHOLDER_RE = re.compile(r"%\((?P<name>[A-Za-z0-9_]+)\)s")


def convert_pyformat_placeholders(sql: str, values: dict[str, object] | None) -> tuple[str, list[object]]:
    bound_values: list[object] = []
    converted: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(sql):
        character = sql[index]
        if quote is not None:
            converted.append(character)
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    converted.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            converted.append(character)
            index += 1
            continue
        match = _PYFORMAT_PLACEHOLDER_RE.match(sql, index)
        if match is None:
            converted.append(character)
            index += 1
            continue
        name = match.group("name")
        if values is None or name not in values:
            raise ExposedHogQLError(f"Missing bound value for Trino parameter '{name}'.")
        bound_values.append(values[name])
        converted.append("?")
        index = match.end()
    if values and not bound_values:
        raise ExposedHogQLError("Trino query has bound values but no parameter placeholders.")
    return "".join(converted), bound_values
