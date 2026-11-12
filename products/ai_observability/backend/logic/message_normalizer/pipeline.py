import dataclasses
from collections import Counter
from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from types import MappingProxyType
from typing import Final

import structlog

from posthog.dataclasses import frozen

from .errors import RecipeRuntimeError
from .expressions import Expr
from .roles import THINKING_ROLE, TOOL_RESULT_ROLE, normalize_role
from .rules import NO_MATCH, DispatchResult, EmitSpec, NoMatch, Recipe, RoleTag, Rule
from .run_limits import charge_messages, charge_operations, charge_output, run_limits
from .scope import Scope
from .values import (
    MISSING,
    CompatMessage,
    JsonValue,
    Missing,
    Value,
    charge_kept_parse,
    is_list,
    is_mapping,
    is_number,
    is_object_like,
    parse_json_text,
    to_json_value,
    to_text,
)

logger = structlog.get_logger(__name__)

MAX_DEPTH: Final = 10
# The operation budget alone still allows seconds of CPU per run, so the time limit is what bounds a run.
TIME_LIMIT_SECONDS: Final = 1.0


@frozen(frozen=False)
class _RunRecord:
    # A probe only asks which recipes match, so it skips the salvage fallback, which serializes whole values.
    salvages: bool = True
    skipped_salvage: bool = False
    matched_recipe_ids: set[str] = dataclasses.field(default_factory=set)
    non_text_content_types: Counter[str] = dataclasses.field(default_factory=Counter)


# One pipeline serves concurrent runs, so each run keeps its record in its own context.
_active_run: ContextVar[_RunRecord | None] = ContextVar("recipe_active_run", default=None)

ROLE_TAG_ROLES: Final[Mapping[RoleTag, str]] = MappingProxyType(
    {
        "user": "user",
        "assistant": "assistant",
        "system": "system",
        "tool": "tool",
        "thinking": THINKING_ROLE,
        "tool_result": TOOL_RESULT_ROLE,
    }
)

_EMPTY_MESSAGE_SLOTS: Final = ("content", "tool_calls", "tool_call_id", "tools")


@frozen
class RunOutcome:
    messages: tuple[CompatMessage, ...]
    recognized: bool
    # Which recipes produced the messages, not what the messages are, so two runs that render the same are equal.
    matched_recipe_ids: frozenset[str] = dataclasses.field(default=frozenset(), compare=False)
    # False when a run without salvage met a value no recipe matched, so its messages leave that value out.
    complete: bool = dataclasses.field(default=True, compare=False)


class SlotCoercer:
    def build_message(self, emit: EmitSpec, scope: Scope, allow_drop: bool = False) -> CompatMessage | None:
        message: dict[str, Value] = {}
        if emit.spread is not None:
            spread = emit.spread.eval(scope)
            if is_mapping(spread):
                charge_output(nodes=len(spread))
                message = {key: value for key, value in spread.items() if not isinstance(value, Missing)}
        role = self._role(emit.role, scope)
        if emit.content is not None:
            self._assign(message, "content", self._content(emit.content.eval(scope)))
        if emit.tool_call_id is not None:
            tool_call_id = emit.tool_call_id.eval(scope)
            if isinstance(tool_call_id, str):
                message["tool_call_id"] = tool_call_id
        if emit.tool_call is not None:
            tool_call = _tool_call(emit.tool_call.eval(scope))
            if tool_call is not None:
                message["tool_calls"] = [tool_call]
        if emit.tool_calls is not None:
            self._assign(message, "tool_calls", _tool_calls(emit.tool_calls.eval(scope)))
        if allow_drop and not any(slot in message for slot in _EMPTY_MESSAGE_SLOTS):
            return None
        content = message.pop("content", None)
        message["role"] = role
        # Renderers expect text, so a message without content gets an empty string.
        message["content"] = "" if content is None else content
        return _json_message(message)

    def stamp(self, message: CompatMessage, emit: EmitSpec, scope: Scope) -> CompatMessage:
        charge_output(nodes=len(message))
        stamped = dict(message)
        if emit.role is not None:
            stamped["role"] = to_json_value(self._role(emit.role, scope))
        if emit.tool_call_id is not None:
            tool_call_id = emit.tool_call_id.eval(scope)
            if isinstance(tool_call_id, str):
                stamped["tool_call_id"] = to_json_value(tool_call_id)
        return stamped

    @staticmethod
    def _assign(message: dict[str, Value], slot: str, value: Value) -> None:
        if isinstance(value, Missing):
            message.pop(slot, None)
        else:
            message[slot] = value

    @staticmethod
    def _role(role: Expr | RoleTag | None, scope: Scope) -> str:
        if role is None:
            return scope.role
        if isinstance(role, str):
            return normalize_role(ROLE_TAG_ROLES[role], scope.role)
        evaluated = role.eval(scope)
        return normalize_role(evaluated, scope.role) if isinstance(evaluated, str) else scope.role

    @staticmethod
    def _content(value: Value) -> Value:
        if value is None:
            return ""
        if isinstance(value, str | Missing):
            return value
        if is_list(value):
            if value and all(isinstance(item, str) for item in value):
                charge_output(nodes=len(value))
                return value[0] if len(value) == 1 else [{"type": "text", "text": item} for item in value]
            return value
        # Reaching here is a recipe bug or a coverage gap, since recipes opt into rendering arbitrary values with
        # `stringify`. Log only the type, because the value may be sensitive. A run logs once with a count per type,
        # because a recipe that matches every item of a list would otherwise log once per item.
        run = _active_run.get()
        if run is None:
            logger.warning("llma_recipe_produced_non_text_content", content_types={_type_name(value): 1})
        else:
            run.non_text_content_types[_type_name(value)] += 1
        return ""


class RecipePipeline:
    def __init__(self, recipes: Iterable[Recipe], time_limit_seconds: float = TIME_LIMIT_SECONDS) -> None:
        self.recipes = tuple(recipes)
        self.coercer = SlotCoercer()
        self.time_limit_seconds = time_limit_seconds

    def run(self, value: Value, default_role: str, *, salvages: bool = True) -> RunOutcome:
        run = _RunRecord(salvages=salvages)
        token = _active_run.set(run)
        try:
            with run_limits(self.time_limit_seconds):
                matched = self._match(value, default_role, 0)
                if not isinstance(matched, NoMatch):
                    return RunOutcome(
                        messages=tuple(matched),
                        recognized=True,
                        matched_recipe_ids=frozenset(run.matched_recipe_ids),
                        complete=not run.skipped_salvage,
                    )
                salvaged = self._salvage(value, default_role) if salvages else NO_MATCH
                run.skipped_salvage = run.skipped_salvage or not salvages
        except RecursionError as error:
            raise RecipeRuntimeError("RecipeNormalizer: the input nests too deeply to normalize") from error
        finally:
            _active_run.reset(token)
            if run.non_text_content_types:
                logger.warning("llma_recipe_produced_non_text_content", content_types=dict(run.non_text_content_types))
        return RunOutcome(
            messages=() if isinstance(salvaged, NoMatch) else tuple(salvaged),
            recognized=False,
            matched_recipe_ids=frozenset(run.matched_recipe_ids),
            complete=not run.skipped_salvage,
        )

    def dispatch(self, value: Value, inherited_role: str, depth: int) -> DispatchResult:
        matched = self._match(value, inherited_role, depth)
        if not isinstance(matched, NoMatch):
            return matched
        run = _active_run.get()
        if run is None or run.salvages:
            return self._salvage(value, inherited_role)
        run.skipped_salvage = True
        return NO_MATCH

    def _match(self, value: Value, inherited_role: str, depth: int) -> DispatchResult:
        if depth > MAX_DEPTH:
            raise RecipeRuntimeError(
                f"RecipeNormalizer: delegation exceeded max depth ({MAX_DEPTH}) — a recipe likely delegates to itself"
            )
        charge_operations(1)
        for recipe in self.recipes:
            for rule in recipe.rules:
                result = self._apply(rule, value, inherited_role, depth)
                if not isinstance(result, NoMatch):
                    _record_match(recipe.id)
                    return result
        return NO_MATCH

    def _apply(self, rule: Rule, value: Value, inherited_role: str, depth: int) -> DispatchResult:
        if not rule.on.matches(value):
            return NO_MATCH
        scope = Scope.for_node(value, inherited_role)
        # Followups are built first, so `produce` may drop an empty primary message only when followups exist.
        followups = rule.build_followups(scope, self)
        primary = rule.produce(scope, self, len(followups) > 0, depth)
        return [*primary, *followups]

    def _salvage(self, value: Value, inherited_role: str) -> DispatchResult:
        if isinstance(value, Missing):
            return NO_MATCH
        role = Scope.for_node(value, inherited_role).role
        content = value.get("content") if is_mapping(value) else None
        charge_messages(1)
        return [{"role": to_json_value(role), "content": to_text(content if isinstance(content, str) else value)}]


def _tool_calls(value: Value) -> Value:
    if not is_list(value):
        return MISSING
    # Each call is a fixed-size wrapper around arguments that the walk or the parse charges, so it counts as one value.
    charge_output(nodes=len(value))
    calls = [call for call in (_tool_call(item) for item in value) if call is not None]
    return calls or MISSING


def _tool_call(value: Value) -> JsonValue | None:
    if not is_mapping(value):
        return None
    call_id = value.get("id")
    id_slot: dict[str, JsonValue] = {"id": call_id} if isinstance(call_id, str) else {}
    function = value.get("function")
    if value.get("type") == "function" and is_object_like(function):
        if not is_mapping(function):
            return None
        name = function.get("name")
        if not isinstance(name, str):
            return None
        arguments = _first_present(function.get("arguments"), {})
        return {"type": "function", **id_slot, "function": {"name": name, "arguments": _parse_arguments(arguments)}}
    name = value.get("name")
    if isinstance(name, str):
        raw = _first_present(value.get("args"), value.get("arguments"), {})
        arguments = _parse_arguments(raw) if isinstance(raw, str) else to_json_value(raw)
        return {"type": "function", **id_slot, "function": {"name": name, "arguments": arguments}}
    return None


def _first_present(*candidates: Value) -> Value:
    return next(candidate for candidate in candidates if candidate is not None and not isinstance(candidate, Missing))


def _parse_arguments(arguments: Value) -> JsonValue:
    if isinstance(arguments, str):
        try:
            parsed = parse_json_text(arguments)
        except ValueError:
            return arguments
        charge_kept_parse(arguments, parsed)
        return parsed
    if is_mapping(arguments) or is_list(arguments):
        return to_json_value(arguments)
    return {}


def _json_message(message: Mapping[str, Value]) -> CompatMessage:
    return {key: to_json_value(value) for key, value in message.items() if not isinstance(value, Missing)}


def _type_name(value: Value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if is_number(value):
        return "number"
    return "object"


def _record_match(recipe_id: str) -> None:
    run = _active_run.get()
    if run is not None:
        run.matched_recipe_ids.add(recipe_id)
