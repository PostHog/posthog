from collections.abc import Callable, Sequence
from typing import Final

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from ...facade import contracts
from ..message_normalizer.errors import RecipeRuntimeError
from ..message_normalizer.normalizer import RecipeNormalizer
from ..message_normalizer.run_limits import time_limit
from ..message_normalizer.values import MISSING, CompatMessage, Value
from .message_lists import conversation_of
from .step_messages import to_messages

logger = structlog.get_logger(__name__)

# One deadline covers compiling the team's recipes and normalizing both sides, so one node read spends at most this
# long in the normalizer, however many recipe runs it makes.
NODE_READ_TIME_LIMIT_SECONDS: Final = 1.0


@frozen
class SideReading:
    """Whether the engine recognized a side. An empty side has nothing to recognize, so it counts as recognized."""

    recognized: bool
    runtime_error: str | None = None


@frozen
class StepReading:
    content: contracts.TraceNodeContent
    input: SideReading
    output: SideReading


@frozen
class _ReadSide:
    side: contracts.TraceMessagesSide | contracts.TraceJsonSide
    reading: SideReading


def step_content(
    kind: contracts.TraceNodeKind,
    node_id: str,
    input_value: Value,
    output_value: Value,
    *,
    build_normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> contracts.TraceNodeContent:
    return read_step(
        kind, node_id, input_value, output_value, build_normalizer=build_normalizer, team_id=team_id
    ).content


def read_step(
    kind: contracts.TraceNodeKind,
    node_id: str,
    input_value: Value,
    output_value: Value,
    *,
    build_normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> StepReading:
    # Building the team's normalizer reads and compiles its recipes, so one node read builds it at most once.
    normalizer = _built_once(build_normalizer)
    input_prefix, output_prefix = f"{node_id}-in", f"{node_id}-out"
    with time_limit(NODE_READ_TIME_LIMIT_SECONDS):
        # Both sides share one deadline, so a side that is already a conversation renders before any team-recipe check
        # on a JSON side can spend the time it needs.
        input_side = _conversation_side(
            kind, node_id, input_value, output_value, "user", input_prefix, normalizer=normalizer, team_id=team_id
        )
        output_side = _conversation_side(
            kind, node_id, output_value, input_value, "assistant", output_prefix, normalizer=normalizer, team_id=team_id
        )
        read_input = (
            input_side
            if input_side is not None
            else _team_recipe_or_json_side(
                kind, node_id, input_value, "user", input_prefix, normalizer=normalizer, team_id=team_id
            )
        )
        read_output = (
            output_side
            if output_side is not None
            else _team_recipe_or_json_side(
                kind, node_id, output_value, "assistant", output_prefix, normalizer=normalizer, team_id=team_id
            )
        )
        return StepReading(
            content=contracts.TraceNodeContent(input=read_input.side, output=read_output.side),
            input=read_input.reading,
            output=read_output.reading,
        )


class _NormalizerUnavailableError(RecipeRuntimeError):
    pass


def _built_once(build: Callable[[], RecipeNormalizer]) -> Callable[[], RecipeNormalizer]:
    # A build that fails would fail again for the other side, so the failure is kept. The first side raises it and
    # reports it, and a later side raises a bounded error so the same failure reaches error tracking once.
    built: list[RecipeNormalizer | Exception] = []

    def normalizer() -> RecipeNormalizer:
        if built:
            result = built[0]
            if isinstance(result, Exception):
                raise _NormalizerUnavailableError(
                    "The team's normalizer failed to build earlier in this read"
                ) from result
            return result
        try:
            team_normalizer = build()
        except Exception as error:
            built.append(error)
            raise
        built.append(team_normalizer)
        return team_normalizer

    return normalizer


def _conversation_side(
    kind: contracts.TraceNodeKind,
    node_id: str,
    value: Value,
    other: Value,
    default_role: str,
    id_prefix: str,
    *,
    normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> _ReadSide | None:
    source = _conversation_source(kind, value, other=other)
    if source is _NOT_A_CONVERSATION:
        return None
    return _guarded(
        lambda: _messages_side(
            source,
            default_role=default_role,
            id_prefix=id_prefix,
            node_id=node_id,
            normalizer=normalizer,
            team_id=team_id,
        ),
        kind,
        value,
        team_id=team_id,
    )


def _team_recipe_or_json_side(
    kind: contracts.TraceNodeKind,
    node_id: str,
    value: Value,
    default_role: str,
    id_prefix: str,
    *,
    normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> _ReadSide:
    def build() -> _ReadSide:
        team_side = _team_recipe_side(
            value,
            default_role=default_role,
            id_prefix=id_prefix,
            node_id=node_id,
            normalizer=normalizer,
            team_id=team_id,
        )
        if team_side is not None:
            return _ReadSide(side=team_side, reading=SideReading(recognized=True))
        return _ReadSide(
            side=contracts.TraceJsonSide(kind="json", value=value),
            reading=SideReading(recognized=not _is_unreadable_json(value)),
        )

    return _guarded(build, kind, value, team_id=team_id)


def _guarded(
    build: Callable[[], _ReadSide],
    kind: contracts.TraceNodeKind,
    value: Value,
    *,
    team_id: int,
) -> _ReadSide:
    # Event data and team recipes can take any shape, so no failure while reading one side may fail the node read.
    try:
        return build()
    except Exception as error:
        # A deadline, budget or nesting bound fails the same node on every read, so only unexpected errors carry a
        # traceback and reach error tracking.
        bounded = isinstance(error, RecipeRuntimeError)
        logger.warning(
            "trace_step_content_fallback",
            team_id=team_id,
            node_kind=kind,
            error_class=type(error).__name__,
            exc_info=not bounded,
        )
        if not bounded:
            capture_exception(error, {"team_id": team_id, "node_kind": kind})
        return _ReadSide(
            side=contracts.TraceJsonSide(kind="json", value=value),
            reading=SideReading(recognized=False, runtime_error=str(error) if bounded else None),
        )


def _is_unreadable_json(value: Value) -> bool:
    # Only an object or an array shows as a JSON tree that a parser could turn into messages. Text, numbers and
    # booleans read fine as they are, and no parser can make a conversation of them.
    return isinstance(value, dict | list) and bool(value)


def _is_empty(value: object) -> bool:
    return value is None or value == ""


# No event value is MISSING, so it marks a side that is not a conversation, while None stays an empty conversation.
_NOT_A_CONVERSATION: Final = MISSING


def _conversation_source(kind: contracts.TraceNodeKind, value: Value, *, other: Value) -> Value:
    # A generation's input is a provider request, so its built-in recipes read it whole.
    if kind == "generation":
        return value
    conversation = conversation_of(value)
    if conversation is not None:
        return conversation
    if (_is_empty(value) or isinstance(value, str)) and conversation_of(other) is not None:
        return value
    return _NOT_A_CONVERSATION


def _messages_side(
    value: Value,
    *,
    default_role: str,
    id_prefix: str,
    node_id: str,
    normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> _ReadSide:
    if _is_empty(value):
        return _ReadSide(
            side=contracts.TraceMessagesSide(kind="messages", messages=[]), reading=SideReading(recognized=True)
        )
    team_normalizer = normalizer()
    outcome = team_normalizer.normalize_messages(value, default_role)
    side = _side_of(outcome.messages, id_prefix=id_prefix, node_id=node_id, team_id=team_id)
    # A team recipe can match and emit only content that renders nothing, which leaves an empty conversation where the
    # value was. A built-in recipe rendering nothing means the messages themselves are empty, which no recipe can fix.
    team_recipe_rendered_nothing = (
        bool(outcome.matched_recipe_ids & team_normalizer.custom_recipe_ids) and not side.messages
    )
    return _ReadSide(side=side, reading=SideReading(recognized=outcome.recognized and not team_recipe_rendered_nothing))


def _team_recipe_side(
    value: Value,
    *,
    default_role: str,
    id_prefix: str,
    node_id: str,
    normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> contracts.TraceMessagesSide | None:
    # A built-in recipe recognizes any list, so only a match by one of the team's own recipes shows that a side the
    # message-list rule rejected is a conversation.
    if _is_empty(value):
        return None
    team_normalizer = normalizer()
    if not team_normalizer.custom_recipe_ids:
        return None
    outcome = team_normalizer.normalize_if_matched(value, default_role, team_normalizer.custom_recipe_ids)
    if outcome is None:
        return None
    side = _side_of(outcome.messages, id_prefix=id_prefix, node_id=node_id, team_id=team_id)
    # A team recipe can match and still emit nothing renderable, such as an object as content, and the raw JSON then
    # shows more than an empty conversation.
    return side if side.messages else None


def _side_of(
    compat: Sequence[CompatMessage], *, id_prefix: str, node_id: str, team_id: int
) -> contracts.TraceMessagesSide:
    messages = to_messages(compat, id_prefix=id_prefix, source_node_id=node_id, team_id=team_id)
    return contracts.TraceMessagesSide(kind="messages", messages=messages)
