import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Final

import structlog

from posthog.dataclasses import frozen

from .errors import RecipeRuntimeError
from .expressions import Expr
from .roles import normalize_role
from .rules import NO_MATCH, DispatchResult, EmitSpec, NoMatch, Recipe, RoleTag, Rule
from .scope import Scope
from .time_limit import time_limit
from .values import (
    MISSING,
    CompatMessage,
    JsonValue,
    Missing,
    Value,
    is_list,
    is_mapping,
    is_number,
    is_object_like,
    to_json_text,
    to_json_value,
)

logger = structlog.get_logger(__name__)

# Both ceilings sit far above what any renderable trace produces. They exist so a pathological team recipe fails
# fast instead of pinning a server worker.
MAX_OPERATIONS: Final = 250_000
MAX_MESSAGES: Final = 25_000
MAX_DEPTH: Final = 10
# The operation budget alone still allows seconds of CPU per run, so the time limit is what bounds a run.
TIME_LIMIT_SECONDS: Final = 1.0

ROLE_TAG_ROLES: Final[Mapping[RoleTag, str]] = MappingProxyType(
    {
        "user": "user",
        "assistant": "assistant",
        "system": "system",
        "tool": "tool",
        "thinking": "assistant (thinking)",
        "tool_result": "assistant (tool result)",
    }
)

_EMPTY_MESSAGE_SLOTS: Final = ("content", "tool_calls", "tool_call_id", "tools")


@frozen
class RunOutcome:
    messages: list[CompatMessage]
    recognized: bool


class ExecutionBudget:
    def __init__(self) -> None:
        self._operations = 0
        self._messages = 0

    def reset(self) -> None:
        self._operations = 0
        self._messages = 0

    def charge_operations(self, count: int) -> None:
        self._operations += count
        if self._operations > MAX_OPERATIONS:
            raise RecipeRuntimeError(
                f"RecipeNormalizer: exceeded the operation budget ({MAX_OPERATIONS}) — a recipe expands this event into too much work"
            )

    def charge_messages(self, count: int) -> None:
        self._messages += count
        if self._messages > MAX_MESSAGES:
            raise RecipeRuntimeError(
                f"RecipeNormalizer: exceeded the message budget ({MAX_MESSAGES}) — a recipe expands this event into too many messages"
            )


class SlotCoercer:
    def build_message(self, emit: EmitSpec, scope: Scope, allow_drop: bool = False) -> CompatMessage | None:
        message: dict[str, Value] = {}
        # The spread goes first, so the explicit slots below override it.
        if emit.spread is not None:
            spread = emit.spread.eval(scope)
            if is_mapping(spread):
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
            # An explicit slot that yields no calls clears any calls the spread put there.
            self._assign(message, "tool_calls", _tool_calls(emit.tool_calls.eval(scope)))
        if allow_drop and not any(slot in message for slot in _EMPTY_MESSAGE_SLOTS):
            return None
        content = message.pop("content", None)
        # Renderers expect text, so a message without content gets an empty string.
        return _json_message({**message, "role": role, "content": "" if content is None else content})

    def stamp(self, message: CompatMessage, emit: EmitSpec, scope: Scope) -> CompatMessage:
        # Puts the parent's role and tool call id on children a `delegateEach` normalized on their own.
        stamped = dict(message)
        if emit.role is not None:
            stamped["role"] = self._role(emit.role, scope)
        if emit.tool_call_id is not None:
            tool_call_id = emit.tool_call_id.eval(scope)
            if isinstance(tool_call_id, str):
                stamped["tool_call_id"] = tool_call_id
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
            # Empty lists stay as they are; a recipe opts into dropping them with `if_empty: ~`.
            if value and all(isinstance(item, str) for item in value):
                return value[0] if len(value) == 1 else [{"type": "text", "text": item} for item in value]
            return value
        # Reaching here is a recipe bug or a coverage gap, since recipes opt into rendering arbitrary values with
        # `stringify`. Log only the type, because the value may be sensitive.
        logger.warning("llma_recipe_produced_non_text_content", content_type=_type_name(value))
        return ""


class RecipePipeline:
    def __init__(self, recipes: Iterable[Recipe], time_limit_seconds: float = TIME_LIMIT_SECONDS) -> None:
        self.recipes = tuple(recipes)
        self.coercer = SlotCoercer()
        self.budget = ExecutionBudget()
        self.time_limit_seconds = time_limit_seconds

    def run(self, value: Value, default_role: str) -> RunOutcome:
        self.budget.reset()
        try:
            with time_limit(self.time_limit_seconds):
                matched = self._match(value, default_role, 0)
                if not isinstance(matched, NoMatch):
                    return RunOutcome(messages=matched, recognized=True)
                salvaged = self._salvage(value, default_role)
        except RecursionError as error:
            raise RecipeRuntimeError("RecipeNormalizer: the input nests too deeply to normalize") from error
        return RunOutcome(messages=[] if isinstance(salvaged, NoMatch) else salvaged, recognized=False)

    def dispatch(self, value: Value, inherited_role: str, depth: int) -> DispatchResult:
        # Delegation salvages an unmatched child, so nested fragments survive instead of being dropped.
        matched = self._match(value, inherited_role, depth)
        return matched if not isinstance(matched, NoMatch) else self._salvage(value, inherited_role)

    def _match(self, value: Value, inherited_role: str, depth: int) -> DispatchResult:
        if depth > MAX_DEPTH:
            raise RecipeRuntimeError(
                f"RecipeNormalizer: delegation exceeded max depth ({MAX_DEPTH}) — a recipe likely delegates to itself"
            )
        self.budget.charge_operations(1)
        for recipe in self.recipes:
            for rule in recipe.rules:
                result = self._apply(rule, value, inherited_role, depth)
                if not isinstance(result, NoMatch):
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
        self.budget.charge_messages(1)
        return [{"role": role, "content": content if isinstance(content, str) else _stringify_content(value)}]


def _stringify_content(value: Value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return to_json_text(value)


def _tool_calls(value: Value) -> Value:
    if not is_list(value):
        return MISSING
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
            return json.loads(arguments)
        except ValueError:
            return arguments
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
