import functools
from collections.abc import Callable
from typing import Final

import structlog

from posthog.exceptions_capture import capture_exception

from ...facade import contracts
from ..message_normalizer.errors import RecipeRuntimeError
from ..message_normalizer.normalizer import RecipeNormalizer
from ..message_normalizer.run_limits import time_limit
from ..message_normalizer.values import Value
from .message_lists import is_message_list
from .step_messages import to_messages

logger = structlog.get_logger(__name__)

# One deadline covers compiling the team's recipes and normalizing both sides, so one node read spends at most this
# long in the normalizer, however many recipe runs it makes.
NODE_READ_TIME_LIMIT_SECONDS: Final = 1.0


def step_content(
    kind: contracts.TraceNodeKind,
    node_id: str,
    input_value: Value,
    output_value: Value,
    *,
    build_normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> contracts.TraceNodeContent:
    # Building the team's normalizer reads and compiles its recipes, so a step whose sides are JSON never builds it.
    normalizer = functools.cache(build_normalizer)
    with time_limit(NODE_READ_TIME_LIMIT_SECONDS):
        return contracts.TraceNodeContent(
            input=_side(
                kind,
                node_id,
                input_value,
                other=output_value,
                default_role="user",
                id_prefix=f"{node_id}-in",
                normalizer=normalizer,
                team_id=team_id,
            ),
            output=_side(
                kind,
                node_id,
                output_value,
                other=input_value,
                default_role="assistant",
                id_prefix=f"{node_id}-out",
                normalizer=normalizer,
                team_id=team_id,
            ),
        )


def _side(
    kind: contracts.TraceNodeKind,
    node_id: str,
    value: Value,
    *,
    other: Value,
    default_role: str,
    id_prefix: str,
    normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> contracts.TraceMessagesSide | contracts.TraceJsonSide:
    # Event data and team recipes can take any shape, so no failure while reading one side may fail the node read.
    try:
        if not _is_messages_side(kind, value, other=other):
            return contracts.TraceJsonSide(kind="json", value=value)
        return _messages_side(
            value,
            default_role=default_role,
            id_prefix=id_prefix,
            node_id=node_id,
            normalizer=normalizer,
            team_id=team_id,
        )
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
        return contracts.TraceJsonSide(kind="json", value=value)


def _is_empty(value: object) -> bool:
    return value is None or value == ""


def _is_messages_side(kind: contracts.TraceNodeKind, value: Value, *, other: Value) -> bool:
    if kind == "generation":
        return True
    if is_message_list(value):
        return True
    return (_is_empty(value) or isinstance(value, str)) and is_message_list(other)


def _messages_side(
    value: Value,
    *,
    default_role: str,
    id_prefix: str,
    node_id: str,
    normalizer: Callable[[], RecipeNormalizer],
    team_id: int,
) -> contracts.TraceMessagesSide:
    if _is_empty(value):
        return contracts.TraceMessagesSide(kind="messages", messages=[])
    compat = normalizer().normalize_messages(value, default_role).messages
    messages = to_messages(compat, id_prefix=id_prefix, source_node_id=node_id, team_id=team_id)
    return contracts.TraceMessagesSide(kind="messages", messages=messages)
