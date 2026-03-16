import enum
import json
import uuid
import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any

from django.conf import settings
from django.http import StreamingHttpResponse

import structlog
from asgiref.sync import async_to_sync as asgi_async_to_sync
from django_redis import get_redis_connection
from pydantic import ValidationError as PydanticValidationError
from rest_framework import exceptions

from posthog.schema import AssistantEventType, AssistantMessage, HumanMessage

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.stream.redis_stream import TaskRunRedisStream, TaskRunStreamError, get_task_run_stream_key
from products.tasks.backend.temporal.client import execute_task_processing_workflow
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.sandbox.mapping import get_sandbox_mapping, set_sandbox_mapping
from ee.hogai.sandbox.types import (
    ACP_METHOD_SESSION_UPDATE,
    ACP_NOTIFICATION_TYPE,
    ACP_SESSION_UPDATE_AGENT_MESSAGE_CHUNK,
    TURN_COMPLETE_METHOD,
    ACPNotification,
    ACPSessionUpdateParams,
    SandboxSeedEvent,
)
from ee.hogai.utils.aio import async_to_sync
from ee.hogai.utils.feature_flags import has_sandbox_mode_feature_flag
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

SANDBOX_TURN_IDLE_TIMEOUT = 60  # seconds of silence before ending the per-turn stream (safety fallback)
SANDBOX_STREAM_TTL = 3600  # seconds before the Redis stream key expires


def handle_sandbox_message(
    conversation: Conversation,
    conversation_id: str,
    content: str,
    user: User,
    team: Team,
    is_new_conversation: bool,
) -> StreamingHttpResponse:
    """Handle a sandbox-mode message: create/resume a task run and stream events back."""
    if not settings.DEBUG and not has_sandbox_mode_feature_flag(team, user):
        raise exceptions.PermissionDenied("Sandbox mode is not enabled for this user.")

    if is_new_conversation:
        conversation.title = content[:80]
        conversation.save(update_fields=["title"])

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
            new_run = task.create_run(
                mode="interactive",
                extra_state={
                    "snapshot_external_id": snapshot_ext_id,
                    "resume_from_run_id": str(task_run.id),
                    "pending_user_message": content,
                },
            )
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

        # Signal the Temporal workflow to send the follow-up message
        try:
            client = sync_connect()
            handle = client.get_workflow_handle(task_run.workflow_id)

            async def _send_signal():
                await handle.signal(ProcessTaskWorkflow.send_followup_message, content)

            asgi_async_to_sync(_send_signal)()
        except Exception as e:
            logger.warning(
                "sandbox_followup_signal_failed",
                run_id=run_id,
                error=str(e),
            )
    else:
        # First message: create task + run
        # TODO(@tatoalo): hardcoding repo for now, already built repo selection wiring
        try:
            task = Task.create_and_run(
                team=team,
                title=content[:80],
                description=content,
                origin_product=Task.OriginProduct.USER_CREATED,
                user_id=user.pk,
                repository="posthog/posthog",
                create_pr=False,
                mode="interactive",
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


def _is_turn_complete(event: dict) -> bool:
    if event.get("type") != ACP_NOTIFICATION_TYPE:
        return False
    notification = event.get("notification", {})
    return notification.get("method") == TURN_COMPLETE_METHOD


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
    agent_text_chunks: list[str] = []

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

            # Accumulate agent text for message persistence
            _accumulate_agent_text(event, agent_text_chunks)

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

        # Persist messages after the turn completes
        if conversation_id:
            agent_text = "".join(agent_text_chunks)
            await _persist_sandbox_turn(conversation_id, user_content, agent_text, team_id=team_id)


def _accumulate_agent_text(event: dict, chunks: list[str]) -> None:
    """Extract agent message text from session/update notifications."""
    if event.get("type") != ACP_NOTIFICATION_TYPE:
        return
    raw_notification = event.get("notification")
    if not isinstance(raw_notification, dict):
        return
    try:
        notification = ACPNotification.model_validate(raw_notification)
    except PydanticValidationError:
        return
    if notification.method != ACP_METHOD_SESSION_UPDATE:
        return
    if not isinstance(notification.params, ACPSessionUpdateParams):
        return
    update = notification.params.update
    if update is None or update.sessionUpdate != ACP_SESSION_UPDATE_AGENT_MESSAGE_CHUNK:
        return
    if update.content and update.content.type == "text" and update.content.text:
        chunks.append(update.content.text)


async def _persist_sandbox_turn(
    conversation_id: str, user_content: str | None, agent_text: str, team_id: int | None = None
) -> None:
    """Persist user and agent messages on the Conversation after a sandbox turn."""
    try:
        lookup: dict[str, Any] = {"id": conversation_id}
        if team_id is not None:
            lookup["team_id"] = team_id
        conversation = await Conversation.objects.aget(**lookup)
        messages: list[dict[str, Any]] = conversation.messages_json or []
        if user_content:
            messages.append(HumanMessage(content=user_content, id=str(uuid.uuid4())).model_dump(exclude_none=True))
        if agent_text:
            messages.append(
                AssistantMessage(content=agent_text, id=f"sandbox-{uuid.uuid4()}").model_dump(exclude_none=True)
            )
        conversation.messages_json = messages
        await conversation.asave(update_fields=["messages_json"])
    except Exception as e:
        logger.warning("persist_sandbox_turn_failed", conversation_id=conversation_id, error=str(e))
