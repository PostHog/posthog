import re
from abc import ABC, abstractmethod
from typing import Final

from posthog.dataclasses import frozen

from .predicates import Pattern
from .run_limits import MAX_PARSE_CHARS, charge_output, check_time_limit
from .scope import Scope
from .values import (
    MISSING,
    Missing,
    Value,
    charge_kept_parse,
    is_list,
    is_mapping,
    parse_json_text,
    read_field,
    read_path,
    to_json_text,
    to_text,
)

STRUCTURED_CONTENT_TYPES: Final = frozenset(
    {"text", "output_text", "input_text", "function", "image", "input_image", "image_url", "file", "audio", "document"}
)
# Structured content is an empty array or one whose first item is an object. `\s` matches what `str.strip` trims,
# and only JSON whitespace may follow the bracket.
_BLOCK_ARRAY_START: Final = re.compile(r"\s*\[[ \t\n\r]*(?=[{\]])")


class Expr(ABC):
    __slots__ = ()

    def eval(self, scope: Scope) -> Value:
        # A team recipe can build one expression that runs for minutes, so every evaluation checks the clock.
        check_time_limit()
        return self._evaluate(scope)

    @abstractmethod
    def _evaluate(self, scope: Scope) -> Value: ...


@frozen
class LiteralExpr(Expr):
    value: Value

    def _evaluate(self, scope: Scope) -> Value:
        return self.value


@frozen
class SelfExpr(Expr):
    def _evaluate(self, scope: Scope) -> Value:
        return scope.value


@frozen
class PathExpr(Expr):
    segments: tuple[str, ...]

    def _evaluate(self, scope: Scope) -> Value:
        return read_path(scope.value, self.segments)


@frozen
class InterpExpr(Expr):
    parts: tuple[str | Expr, ...]

    def _evaluate(self, scope: Scope) -> Value:
        # `to_text` charges the evaluated parts, and the literal parts are charged here, so the join is paid for.
        charge_output(nodes=len(self.parts), chars=sum(len(part) for part in self.parts if isinstance(part, str)))
        return "".join([part if isinstance(part, str) else to_text(part.eval(scope)) for part in self.parts])


@frozen
class ArrayExpr(Expr):
    items: tuple[Expr, ...]

    def _evaluate(self, scope: Scope) -> Value:
        charge_output(nodes=len(self.items))
        return [item.eval(scope) for item in self.items]


@frozen
class ObjectExpr(Expr):
    fields: tuple[tuple[str, Expr], ...]

    def _evaluate(self, scope: Scope) -> Value:
        charge_output(nodes=len(self.fields))
        return {key: expr.eval(scope) for key, expr in self.fields}


@frozen
class CoalesceExpr(Expr):
    source: Expr

    def _evaluate(self, scope: Scope) -> Value:
        candidates = self.source.eval(scope)
        if not is_list(candidates):
            return MISSING
        return next((value for value in candidates if not _is_nullish(value)), MISSING)


@frozen
class JoinExpr(Expr):
    source: Expr
    sep: Expr | None
    field: Expr | None

    def _evaluate(self, scope: Scope) -> Value:
        items = self.source.eval(scope)
        if not is_list(items):
            return ""
        sep = self.sep.eval(scope) if self.sep is not None else MISSING
        field = self.field.eval(scope) if self.field is not None else MISSING
        separator = sep if isinstance(sep, str) else "\n"
        # The separator repeats between every pair of items, so a nested join grows multiplicatively. The repeats are
        # charged before the join allocates, which stops the run before it builds an oversized string.
        charge_output(nodes=len(items), chars=len(separator) * max(len(items) - 1, 0))
        return separator.join([to_text(read_field(item, field) if isinstance(field, str) else item) for item in items])


@frozen
class OmitExpr(Expr):
    source: Expr
    keys: Expr | None

    def _evaluate(self, scope: Scope) -> Value:
        source = self.source.eval(scope)
        if not is_mapping(source):
            return {}
        raw_keys = self.keys.eval(scope) if self.keys is not None else MISSING
        charge_output(nodes=len(source) + (len(raw_keys) if is_list(raw_keys) else 0))
        omitted = {key for key in raw_keys if isinstance(key, str)} if is_list(raw_keys) else set()
        return {key: value for key, value in source.items() if key not in omitted}


@frozen
class SelectExpr(Expr):
    source: Expr
    where: Pattern | None
    pluck: Expr | None
    if_empty: Expr | None

    def _evaluate(self, scope: Scope) -> Value:
        items = self.source.eval(scope)
        if not is_list(items):
            return _non_list_fallback(self.if_empty, scope)
        charge_output(nodes=len(items))
        kept: list[Value] = [item for item in items if self.where is None or self.where.matches(item)]
        if self.pluck is not None:
            charge_output(nodes=len(kept))
            plucked = (self.pluck.eval(scope.with_input(item)) for item in kept)
            kept = [value for value in plucked if not _is_nullish(value)]
        return _empty_fallback(kept, self.if_empty, scope)


@frozen
class RejectExpr(Expr):
    source: Expr
    where: Pattern | None
    if_empty: Expr | None

    def _evaluate(self, scope: Scope) -> Value:
        items = self.source.eval(scope)
        if not is_list(items):
            return _non_list_fallback(self.if_empty, scope)
        charge_output(nodes=len(items))
        kept: list[Value] = [item for item in items if self.where is None or not self.where.matches(item)]
        return _empty_fallback(kept, self.if_empty, scope)


@frozen
class StringifyExpr(Expr):
    source: Expr

    def _evaluate(self, scope: Scope) -> Value:
        value = self.source.eval(scope)
        if value is None or isinstance(value, str | Missing) or is_list(value):
            return value
        return to_json_text(value)


@frozen
class TryParseStructuredContentExpr(Expr):
    source: Expr

    def _evaluate(self, scope: Scope) -> Value:
        value = self.source.eval(scope)
        return _parse_structured_content(value) if isinstance(value, str) else value


def _is_nullish(value: Value) -> bool:
    return value is None or isinstance(value, Missing)


def _non_list_fallback(if_empty: Expr | None, scope: Scope) -> Value:
    fallback = if_empty.eval(scope) if if_empty is not None else MISSING
    return [] if _is_nullish(fallback) else fallback


def _empty_fallback(result: list[Value], if_empty: Expr | None, scope: Scope) -> Value:
    if result or if_empty is None:
        return result
    fallback = if_empty.eval(scope)
    # A recipe writes `if_empty: ~` to drop the slot entirely, so a null fallback becomes missing.
    return MISSING if fallback is None else fallback


def _parse_structured_content(content: str) -> Value:
    # Checked before trimming, so text that cannot be structured content is never copied or parsed.
    if len(content) > MAX_PARSE_CHARS or not _BLOCK_ARRAY_START.match(content):
        return content
    try:
        parsed = parse_json_text(content.strip())
    except ValueError:
        return content
    if isinstance(parsed, list) and all(_is_structured_block(item) for item in parsed):
        charge_kept_parse(content, parsed)
        return parsed
    return content


def _is_structured_block(item: Value) -> bool:
    if not is_mapping(item):
        return False
    block_type = item.get("type")
    return isinstance(block_type, str) and block_type in STRUCTURED_CONTENT_TYPES
