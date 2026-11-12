from abc import ABC, abstractmethod
from typing import Final, Literal, Protocol

from posthog.dataclasses import frozen

from .expressions import Expr
from .predicates import Pattern
from .run_limits import charge_messages, charge_operations
from .scope import Scope
from .values import CompatMessage, Value, is_list


class NoMatch:
    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_MATCH"


# Tells "no rule matched, keep scanning" apart from "a rule matched and produced no messages".
NO_MATCH: Final = NoMatch()

type DispatchResult = list[CompatMessage] | NoMatch
type RoleTag = Literal["user", "assistant", "system", "tool", "thinking", "tool_result"]


@frozen
class EmitSpec:
    role: Expr | RoleTag | None = None
    content: Expr | None = None
    tool_call: Expr | None = None
    tool_calls: Expr | None = None
    tool_call_id: Expr | None = None
    spread: Expr | None = None


@frozen
class StaticFollowup:
    emit: EmitSpec


@frozen
class ExpandFollowup:
    source: Expr
    each: EmitSpec


type Followup = StaticFollowup | ExpandFollowup


class MessageBuilder(Protocol):
    def build_message(self, emit: EmitSpec, scope: Scope, allow_drop: bool = False) -> CompatMessage | None: ...

    def stamp(self, message: CompatMessage, emit: EmitSpec, scope: Scope) -> CompatMessage: ...


# Rules see the pipeline only through this protocol, so this module never imports the runtime.
class DispatchEngine(Protocol):
    @property
    def coercer(self) -> MessageBuilder: ...

    def dispatch(self, value: Value, inherited_role: str, depth: int) -> DispatchResult: ...


@frozen
class Rule(ABC):
    on: Pattern
    followups: tuple[Followup, ...]

    @abstractmethod
    def produce(self, scope: Scope, engine: DispatchEngine, allow_drop: bool, depth: int) -> list[CompatMessage]: ...

    def build_followups(self, scope: Scope, engine: DispatchEngine) -> list[CompatMessage]:
        messages: list[CompatMessage] = []
        for followup in self.followups:
            match followup:
                case StaticFollowup(emit=emit):
                    self._append_built(messages, engine, emit, scope, allow_drop=True)
                case ExpandFollowup(source=source, each=each):
                    items = source.eval(scope)
                    if not is_list(items):
                        continue
                    # Charged before the walk, so an expansion over a huge list trips the budget first.
                    charge_operations(len(items))
                    for item in items:
                        self._append_built(messages, engine, each, scope.with_input(item), allow_drop=False)
        return messages

    @staticmethod
    def _append_built(
        messages: list[CompatMessage], engine: DispatchEngine, emit: EmitSpec, scope: Scope, allow_drop: bool
    ) -> None:
        message = engine.coercer.build_message(emit, scope, allow_drop)
        if message is not None:
            charge_messages(1)
            messages.append(message)


@frozen
class EmitRule(Rule):
    emit: EmitSpec

    def produce(self, scope: Scope, engine: DispatchEngine, allow_drop: bool, depth: int) -> list[CompatMessage]:
        messages: list[CompatMessage] = []
        self._append_built(messages, engine, self.emit, scope, allow_drop)
        return messages


@frozen
class DelegateRule(Rule):
    source: Expr

    def produce(self, scope: Scope, engine: DispatchEngine, allow_drop: bool, depth: int) -> list[CompatMessage]:
        result = engine.dispatch(self.source.eval(scope), scope.role, depth + 1)
        return [] if isinstance(result, NoMatch) else result


@frozen
class DelegateEachRule(Rule):
    source: Expr
    stamp: EmitSpec | None

    def produce(self, scope: Scope, engine: DispatchEngine, allow_drop: bool, depth: int) -> list[CompatMessage]:
        items = self.source.eval(scope)
        if not is_list(items):
            return []
        messages: list[CompatMessage] = []
        for item in items:
            result = engine.dispatch(item, scope.role, depth + 1)
            if not isinstance(result, NoMatch):
                messages.extend(result)
        if self.stamp is None:
            return messages
        stamp = self.stamp
        return [engine.coercer.stamp(message, stamp, scope) for message in messages]


@frozen
class Recipe:
    id: str
    rules: tuple[Rule, ...]
