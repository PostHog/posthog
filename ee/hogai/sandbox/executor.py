import enum
import json
import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any

from django.conf import settings
from django.http import StreamingHttpResponse

import structlog
from asgiref.sync import async_to_sync as asgi_async_to_sync
from django_redis import get_redis_connection
from rest_framework import exceptions

from posthog.schema import AgentMode, AssistantEventType, MaxBillingContext, MaxUIContext

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.stream.redis_stream import TaskRunRedisStream, TaskRunStreamError, get_task_run_stream_key
from products.tasks.backend.temporal.client import execute_task_processing_workflow
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.sandbox.agent_runtime_config import build_posthog_ai_claude_code_config
from ee.hogai.sandbox.context_builder import build_sandbox_system_reminder_sync
from ee.hogai.sandbox.legacy_history import format_legacy_history_for_sandbox
from ee.hogai.sandbox.mapping import get_sandbox_mapping, set_sandbox_mapping
from ee.hogai.sandbox.turn_builder import SandboxTurnBuilder, build_human_message
from ee.hogai.sandbox.types import ACP_NOTIFICATION_TYPE, SandboxSeedEvent, is_turn_complete
from ee.hogai.utils.aio import async_to_sync
from ee.hogai.utils.feature_flags import has_sandbox_mode_feature_flag
from ee.models.assistant import Conversation, CoreMemory

logger = structlog.get_logger(__name__)

SANDBOX_TURN_IDLE_TIMEOUT = 60  # seconds of silence before ending the per-turn stream (safety fallback)
SANDBOX_STREAM_TTL = 3600  # seconds before the Redis stream key expires


def _build_first_turn_payload(
    *,
    content: str,
    user: User,
    team: Team,
    conversation: Conversation,
    ui_context: MaxUIContext | dict | None,
    billing_context: MaxBillingContext | dict | None,
    contextual_tools: dict[str, Any] | None,
    agent_mode: AgentMode | str | None,
    is_existing_conversation: bool,
) -> str:
    """Build the user-message text for the first turn of a sandbox run.

    Concatenates (in order):

    1. A ``<system_reminder>`` block with dynamic context — what the user is
       viewing, billing state, contextual tools, selected mode, core memory.
       Identity / persona text lives in the system prompt via
       ``--claudeCodeConfig`` and is intentionally *not* repeated here.
    2. A formatted transcript of any prior LangGraph conversation history (only
       when the user is continuing an existing non-sandbox conversation).
    3. The user's new message.
    """
    parts: list[str] = []

    core_memory = CoreMemory.objects.filter(team=team).first()
    reminder = build_sandbox_system_reminder_sync(
        team=team,
        user=user,
        ui_context=ui_context,
        billing_context=billing_context,
        contextual_tools=contextual_tools,
        agent_mode=agent_mode,
        core_memory=core_memory,
        include_identity=True,
    )
    if reminder:
        parts.append(reminder)

    if is_existing_conversation:
        legacy = format_legacy_history_for_sandbox(conversation)
        if legacy:
            parts.append(legacy)

    parts.append(content)
    return "\n\n".join(parts)


def _build_followup_payload(
    *,
    content: str,
    user: User,
    team: Team,
    ui_context: MaxUIContext | dict | None,
    billing_context: MaxBillingContext | dict | None,
    contextual_tools: dict[str, Any] | None,
    agent_mode: AgentMode | str | None,
) -> str:
    """Build the user-message text for a follow-up turn in an existing run.

    Identity and core memory are already in the running session, so the reminder
    here is dynamic-only (UI / billing / tools / mode).
    """
    reminder = build_sandbox_system_reminder_sync(
        team=team,
        user=user,
        ui_context=ui_context,
        billing_context=billing_context,
        contextual_tools=contextual_tools,
        agent_mode=agent_mode,
        core_memory=None,
        include_identity=False,
    )
    if reminder:
        return f"{reminder}\n\n{content}"
    return content


def handle_sandbox_message(
    conversation: Conversation,
    conversation_id: str,
    content: str,
    user: User,
    team: Team,
    is_new_conversation: bool,
    repository: str | None = None,
    ui_context: MaxUIContext | dict | None = None,
    billing_context: MaxBillingContext | dict | None = None,
    contextual_tools: dict[str, Any] | None = None,
    agent_mode: AgentMode | str | None = None,
) -> StreamingHttpResponse:
    """Handle a sandbox-mode message: create/resume a task run and stream events back."""
    if not settings.DEBUG and not has_sandbox_mode_feature_flag(team, user):
        raise exceptions.PermissionDenied("Sandbox mode is not enabled for this user.")

    if is_new_conversation:
        conversation.title = content[:80]
        conversation.save(update_fields=["title"])

    conversation.status = Conversation.Status.IN_PROGRESS
    conversation.save(update_fields=["status", "updated_at"])

    mapping = get_sandbox_mapping(conversation_id)

    # Reconstruct mapping from conversation fields if Redis expired
    if not mapping and conversation.sandbox_task_id and conversation.sandbox_run_id:
        mapping = {
            "task_id": str(conversation.sandbox_task_id),
            "run_id": str(conversation.sandbox_run_id),
        }

    start_id = "0"

    if mapping:
        run_id = mapping["run_id"]
        start_id = _get_latest_stream_id(run_id)

        try:
            task_run = TaskRun.objects.select_related("task").get(id=run_id, team=team)
        except TaskRun.DoesNotExist:
            raise exceptions.ValidationError("Sandbox session no longer exists.")

        if task_run.is_terminal:
            snapshot_ext_id = (task_run.state or {}).get("snapshot_external_id")
            if not snapshot_ext_id:
                raise exceptions.ValidationError("Sandbox session has ended and no snapshot is available.")

            task = task_run.task
            # Inject the system_reminder into the pending message so the agent gets
            # dynamic context on the first turn of the resumed sandbox too.
            resume_payload_text = _build_followup_payload(
                content=content,
                user=user,
                team=team,
                ui_context=ui_context,
                billing_context=billing_context,
                contextual_tools=contextual_tools,
                agent_mode=agent_mode,
            )
            resumed_state: dict[str, Any] = {
                "snapshot_external_id": snapshot_ext_id,
                "resume_from_run_id": str(task_run.id),
                "pending_user_message": resume_payload_text,
            }
            # Propagate the claude_code_config so the resumed sandbox keeps the
            # PostHog AI system prompt (Code-tasks runs don't set this key and
            # therefore retain default behavior).
            prior_config = (task_run.state or {}).get("claude_code_config_json")
            if prior_config:
                resumed_state["claude_code_config_json"] = prior_config
            new_run = task.create_run(mode="interactive", extra_state=resumed_state)
            run_id = str(new_run.id)

            conversation.sandbox_run_id = new_run.id
            conversation.save(update_fields=["sandbox_run_id"])

            set_sandbox_mapping(conversation_id, str(task.id), run_id)

            execute_task_processing_workflow(
                task_id=str(task.id),
                run_id=run_id,
                team_id=task.team_id,
                user_id=user.pk,
                create_pr=False,
            )

            _seed_sandbox_stream(run_id)
            start_id = "0"

            conv_data = json.dumps(ConversationMinimalSerializer(conversation).data)
            logger.info(
                "sandbox_view_returning_resume_stream",
                run_id=run_id,
                conversation_id=conversation_id,
            )
            return _make_streaming_response(
                lambda: _sandbox_stream(conv_data, run_id, start_id, conversation_id, content, team_id=team.id)
            )

        # Signal the Temporal workflow to send the follow-up message.
        # Prepend the per-turn system_reminder so the agent always sees current
        # UI / billing / mode state when responding to the next user turn.
        followup_payload = _build_followup_payload(
            content=content,
            user=user,
            team=team,
            ui_context=ui_context,
            billing_context=billing_context,
            contextual_tools=contextual_tools,
            agent_mode=agent_mode,
        )
        try:
            client = sync_connect()
            handle = client.get_workflow_handle(task_run.workflow_id)

            async def _send_signal():
                await handle.signal(ProcessTaskWorkflow.send_followup_message, followup_payload)

            asgi_async_to_sync(_send_signal)()
        except Exception as e:
            logger.warning(
                "sandbox_followup_signal_failed",
                run_id=run_id,
                error=str(e),
            )
    else:
        # First message: create task + run with PostHog AI system prompt
        # (via --claudeCodeConfig) plus a system_reminder block carrying
        # dynamic per-turn context.
        first_turn_text = _build_first_turn_payload(
            content=content,
            user=user,
            team=team,
            conversation=conversation,
            ui_context=ui_context,
            billing_context=billing_context,
            contextual_tools=contextual_tools,
            agent_mode=agent_mode,
            is_existing_conversation=not is_new_conversation,
        )
        claude_code_config_json = json.dumps(build_posthog_ai_claude_code_config())
        try:
            task = Task.create_and_run(
                team=team,
                title=content[:80],
                description=first_turn_text,
                origin_product=Task.OriginProduct.USER_CREATED,
                user_id=user.pk,
                repository=repository,
                create_pr=False,
                mode="interactive",
                extra_state={"claude_code_config_json": claude_code_config_json},
                start_workflow=True,
            )
        except ValueError:
            raise exceptions.ValidationError("Failed to create sandbox task.")

        task_run_or_none = task.latest_run
        if not task_run_or_none:
            raise exceptions.ValidationError("Failed to create sandbox task run.")
        task_run = task_run_or_none

        run_id = str(task_run.id)
        set_sandbox_mapping(conversation_id, str(task.id), run_id)

        conversation.sandbox_task_id = task.id
        conversation.sandbox_run_id = task_run.id
        conversation.save(update_fields=["sandbox_task_id", "sandbox_run_id"])

        _seed_sandbox_stream(run_id)

    conv_data = json.dumps(ConversationMinimalSerializer(conversation).data)

    logger.info(
        "sandbox_view_returning_stream",
        run_id=run_id,
        conversation_id=conversation_id,
        start_id=start_id,
        gateway=settings.SERVER_GATEWAY_INTERFACE,
    )
    return _make_streaming_response(
        lambda: _sandbox_stream(conv_data, run_id, start_id, conversation_id, content, team_id=team.id)
    )


def _make_streaming_response(
    async_generator_factory: Callable[[], AsyncGenerator[bytes, None]],
) -> StreamingHttpResponse:
    """Create a StreamingHttpResponse that works under both ASGI and WSGI."""
    return StreamingHttpResponse(
        (
            async_generator_factory()
            if settings.SERVER_GATEWAY_INTERFACE == "ASGI"
            else async_to_sync(async_generator_factory)
        ),
        content_type="text/event-stream",
    )


def _get_latest_stream_id(run_id: str) -> str:
    """Return the latest entry ID in the task-run Redis stream.

    Used for follow-up messages so we only read events generated AFTER
    the current position (avoiding replay of previous turns).
    """
    stream_key = get_task_run_stream_key(run_id)
    conn = get_redis_connection("default")
    try:
        entries = conn.xrevrange(stream_key, count=1)
        if entries:
            return entries[0][0].decode()
    except Exception:
        logger.warning("_get_latest_stream_id_failed", run_id=run_id, exc_info=True)
    return "0"


def _seed_sandbox_stream(run_id: str) -> None:
    """Write a seed event to the Redis stream so it exists before the relay starts.

    Uses the sync Redis connection (safe in WSGI context).  The seed event has
    type=STREAM_STATUS with a non-terminal status, so ``read_stream`` silently
    skips it.
    """
    stream_key = get_task_run_stream_key(run_id)
    conn = get_redis_connection("default")
    conn.xadd(
        stream_key,
        {"data": SandboxSeedEvent().model_dump_json()},
        maxlen=2000,
    )
    conn.expire(stream_key, SANDBOX_STREAM_TTL)


_is_turn_complete = is_turn_complete


async def _sandbox_stream(
    conv_data: str,
    run_id: str,
    start_id: str = "0",
    conversation_id: str | None = None,
    user_content: str | None = None,
    team_id: int | None = None,
) -> AsyncGenerator[bytes, None]:
    """Stream sandbox events from Redis to the browser as SSE.

    Reads events in a background task and funnels them through an
    :class:`asyncio.Queue`.  An idle timeout on the *queue* (not on the
    async-generator) detects when the agent's turn is complete without
    corrupting the underlying Redis reader.

    Args:
        conv_data: Pre-serialized conversation JSON (serialized in sync context).
        run_id: The TaskRun ID whose Redis stream to read from.
        start_id: Redis stream ID to start reading from.
            ``"0"`` replays from the beginning (first message).
            A specific ID resumes from that position (follow-up messages).
        conversation_id: If provided, persist messages on the Conversation after the turn.
        user_content: The user message content to persist alongside the agent response.
    """
    logger.info("sandbox_stream_started", run_id=run_id, start_id=start_id)

    # Emit conversation event so the frontend gets the conversation ID
    yield f"event: {AssistantEventType.CONVERSATION}\ndata: {conv_data}\n\n".encode()

    stream_key = get_task_run_stream_key(run_id)
    redis_stream = TaskRunRedisStream(stream_key)

    if not await redis_stream.wait_for_stream():
        logger.warning("sandbox_stream_wait_timeout", stream_key=stream_key, run_id=run_id)
        error_data = json.dumps({"type": "generation_error"})
        yield f"event: {AssistantEventType.STATUS}\ndata: {error_data}\n\n".encode()
        return

    logger.info("sandbox_stream_connected", stream_key=stream_key)

    # Use a queue to decouple the idle-timeout from the async generator.
    # asyncio.wait_for on __anext__() would cancel and close the generator,
    # so we run the reader in a background task instead.
    class _Sentinel(enum.Enum):
        END = "end"

    event_queue: asyncio.Queue[dict[str, Any] | _Sentinel] = asyncio.Queue()

    async def _reader() -> None:
        try:
            async for ev in redis_stream.read_stream(start_id=start_id):
                await event_queue.put(ev)
        except TaskRunStreamError as exc:
            await event_queue.put({"_error": str(exc)})
        finally:
            await event_queue.put(_Sentinel.END)

    reader_task = asyncio.create_task(_reader())
    turn_builder = SandboxTurnBuilder()

    try:
        event_count = 0
        saw_data = False
        while True:
            try:
                event = await asyncio.wait_for(
                    event_queue.get(),
                    timeout=SANDBOX_TURN_IDLE_TIMEOUT,
                )
            except TimeoutError:
                if saw_data:
                    logger.info("sandbox_stream_turn_idle", run_id=run_id, total_events=event_count)
                    break
                # Haven't seen any data yet; keep waiting (sandbox still booting)
                continue

            if isinstance(event, _Sentinel):
                logger.info("sandbox_stream_completed", run_id=run_id, total_events=event_count)
                break

            if "_error" in event:
                logger.warning("sandbox_stream_error", run_id=run_id, error=event["_error"])
                error_data = json.dumps({"type": "generation_error"})
                yield f"event: {AssistantEventType.STATUS}\ndata: {error_data}\n\n".encode()
                break

            event_count += 1
            saw_data = True

            # Accumulate structured messages (assistant text, reasoning, tool
            # calls) for persistence to Conversation.messages_json at end of turn.
            turn_builder.feed(event)

            if event_count <= 3:
                logger.info(
                    "sandbox_stream_event",
                    run_id=run_id,
                    event_count=event_count,
                    event_type=event.get("type"),
                    notification_method=(
                        event.get("notification", {}).get("method")
                        if event.get("type") == ACP_NOTIFICATION_TYPE
                        else None
                    ),
                )
            event_data = json.dumps(event)
            yield f"event: {AssistantEventType.SANDBOX}\ndata: {event_data}\n\n".encode()

            if _is_turn_complete(event):
                logger.info("sandbox_stream_turn_complete", run_id=run_id, total_events=event_count)
                break
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass

        # Persist messages after the turn completes.
        if conversation_id:
            turn_messages = turn_builder.finalize()
            await _persist_sandbox_turn(conversation_id, user_content, turn_messages, team_id=team_id)


async def _persist_sandbox_turn(
    conversation_id: str,
    user_content: str | None,
    turn_messages: list[dict[str, Any]],
    team_id: int | None = None,
) -> None:
    """Persist the user message and the structured agent turn on the Conversation.

    ``turn_messages`` is the list produced by :class:`SandboxTurnBuilder` —
    typically an ``AssistantMessage`` (with any ``tool_calls`` attached),
    interleaved ``ReasoningMessage`` entries, and trailing
    ``AssistantToolCallMessage`` records carrying tool output.

    The conversation's status is always reset to ``IDLE`` so a persistence
    failure can't leave the row stuck IN_PROGRESS.
    """
    lookup: dict[str, Any] = {"id": conversation_id}
    if team_id is not None:
        lookup["team_id"] = team_id

    try:
        conversation = await Conversation.objects.aget(**lookup)
        messages: list[dict[str, Any]] = list(conversation.messages_json or [])
        if user_content:
            messages.append(build_human_message(user_content))
        messages.extend(turn_messages)
        conversation.messages_json = messages
        conversation.status = Conversation.Status.IDLE
        await conversation.asave(update_fields=["messages_json", "status"])
    except Exception as e:
        logger.warning("persist_sandbox_turn_failed", conversation_id=conversation_id, error=str(e))
        try:
            await Conversation.objects.filter(**lookup).aupdate(status=Conversation.Status.IDLE)
        except Exception:
            logger.exception("persist_sandbox_turn_status_reset_failed", conversation_id=conversation_id)
