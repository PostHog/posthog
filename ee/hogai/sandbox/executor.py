import enum
import json
import uuid
import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any

from django.conf import settings
from django.http import StreamingHttpResponse

import requests as http_requests
import structlog
import posthoganalytics
from asgiref.sync import async_to_sync as asgi_async_to_sync
from django_redis import get_redis_connection
from pydantic import ValidationError as PydanticValidationError
from rest_framework import exceptions

from posthog.schema import AssistantEventType, AssistantMessage, HumanMessage

from posthog.event_usage import groups
from posthog.models.team.team import Team
from posthog.models.user import User

from products.tasks.backend.api import TaskRunViewSet
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.connection_token import create_sandbox_connection_token
from products.tasks.backend.stream.redis_stream import TaskRunRedisStream, TaskRunStreamError, get_task_run_stream_key
from products.tasks.backend.temporal.client import execute_task_processing_workflow, signal_task_followup_message
from products.tasks.backend.temporal.process_task.utils import parse_run_state

from ee.hogai.api.serializers import ConversationMinimalSerializer
from ee.hogai.chat_agent.sandbox_prompt import build_posthog_ai_system_prompt
from ee.hogai.sandbox.context_wrapper import AttachedContext, prune_repeated_entity_refs, wrap_user_message
from ee.hogai.sandbox.mapping import get_sandbox_mapping, set_sandbox_mapping
from ee.hogai.sandbox.types import (
    ACP_METHOD_SESSION_UPDATE,
    ACP_NOTIFICATION_TYPE,
    ACP_SESSION_UPDATE_AGENT_MESSAGE_CHUNK,
    ACPNotification,
    ACPSessionUpdateParams,
    SandboxSeedEvent,
    is_turn_complete,
)
from ee.hogai.utils.aio import async_to_sync
from ee.models.assistant import Conversation

logger = structlog.get_logger(__name__)

SANDBOX_TURN_IDLE_TIMEOUT = 60  # seconds of silence before ending the per-turn stream (safety fallback)
SANDBOX_STREAM_TTL = 3600  # seconds before the Redis stream key expires

# Telemetry: fires when a sandbox turn's message is sent (first or follow-up). The sandbox
# runtime carries an `execution_type: "sandbox"` property on this event (02_CORE § 10) so the
# existing LLM-analytics dashboards keep matching on the event name.
#
# Name reconciliation (02_CORE § 10, I2.5 → I2.7): the LangGraph path has NO canonical
# "prompt sent" event to reuse — its analytics emit at *turn completion* via
# `_report_conversation_state("chat with ai", ...)` (ee/hogai/chat_agent/runner.py), with
# prompt/output/is_new_conversation fields. That is a different lifecycle point (after the turn,
# not at send) and a different shape, so reusing its name would misrepresent the event. We keep
# the dedicated "prompt sent" name for the at-send sandbox signal and document the divergence
# here rather than collapsing two semantically distinct events into one.
PROMPT_SENT_EVENT = "prompt sent"


def handle_sandbox_message(
    conversation: Conversation,
    conversation_id: str,
    content: str,
    user: User,
    team: Team,
    is_new_conversation: bool,
    attached_context: list[AttachedContext] | None = None,
) -> StreamingHttpResponse:
    """Handle a sandbox-mode message: create/resume a task run and stream events back."""
    attached_context = attached_context or []
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

        # Every follow-up turn wraps + dedupes its content the same way the first turn does, then
        # persists the full undeduped structured context as a raw-audit copy. `prior=[]` dedupes
        # only within this batch — walking prior S3 user_message refs is deferred (02_CORE § 4 note).
        wrapped_content = wrap_user_message(content, prune_repeated_entity_refs(attached_context, prior=[]))
        undeduped_context = [item.model_dump(exclude_none=True) for item in attached_context]

        if task_run.is_terminal:
            # Terminal Run → create a NEW Run that resumes from the prior one. The new Run carries the
            # wrapped follow-up as its pending message and replays the snapshot + system prompt.
            snapshot_ext_id = (task_run.state or {}).get("snapshot_external_id")
            if not snapshot_ext_id:
                raise exceptions.ValidationError("Sandbox session has ended and no snapshot is available.")

            system_prompt = asgi_async_to_sync(build_posthog_ai_system_prompt)(team, user)

            task = task_run.task
            new_run = task.create_run(
                mode="interactive",
                extra_state={
                    "snapshot_external_id": snapshot_ext_id,
                    "resume_from_run_id": str(task_run.id),
                    "pending_user_message": wrapped_content,
                    "initial_permission_mode": "default",
                    "system_prompt": system_prompt,
                    "attached_context": undeduped_context,
                },
            )
            run_id = str(new_run.id)

            # Narrow update_fields: only the run pointer moves; the task pointer is unchanged.
            conversation.sandbox_run_id = new_run.id
            conversation.save(update_fields=["sandbox_run_id"])

            set_sandbox_mapping(conversation_id, str(task.id), run_id)

            # Force "full" MCP scopes (decision 10) — the workflow entrypoint defaults to "read_only",
            # which would silently strip the agent's write tools on the resumed Run.
            execute_task_processing_workflow(
                task_id=str(task.id),
                run_id=run_id,
                team_id=task.team_id,
                user_id=user.pk,
                create_pr=False,
                posthog_mcp_scopes="full",
            )

            _seed_sandbox_stream(run_id)
            start_id = "0"

            _emit_prompt_sent(
                team=team,
                user=user,
                conversation_id=conversation_id,
                attached_context=attached_context,
                just_created_run=True,
            )

            conv_data = json.dumps(ConversationMinimalSerializer(conversation).data)
            logger.info(
                "sandbox_view_returning_resume_stream",
                run_id=run_id,
                conversation_id=conversation_id,
            )
            return _make_streaming_response(
                lambda: _sandbox_stream(conv_data, run_id, start_id, conversation_id, content, team_id=team.id)
            )

        # In-progress Run → queue a user_message follow-up via the existing async signal mechanism.
        # This is ASYNC/QUEUED (returns {queued: true}); it does NOT synchronously proxy to the sandbox.
        # The frontend watches the open stream for the agent's reply (02_CORE § 5.2). We reuse the Run.
        _persist_run_attached_context(task_run, undeduped_context)
        try:
            signal_task_followup_message(task_run.workflow_id, wrapped_content, [])
        except Exception as e:
            logger.warning(
                "sandbox_followup_signal_failed",
                run_id=run_id,
                error=str(e),
            )

        _emit_prompt_sent(
            team=team,
            user=user,
            conversation_id=conversation_id,
            attached_context=attached_context,
            just_created_run=False,
        )
    else:
        # First message: create task + run. No-Repository Mode — the sandbox runtime has no repo,
        # no GitHub integration, and never opens a PR (04_PROMPTS § 2.3).
        wrapped_content = wrap_user_message(content, prune_repeated_entity_refs(attached_context, prior=[]))
        system_prompt = asgi_async_to_sync(build_posthog_ai_system_prompt)(team, user)

        try:
            task = Task.create_and_run(
                team=team,
                title=content[:80],
                description=wrapped_content,
                origin_product=Task.OriginProduct.USER_CREATED,
                user_id=user.pk,
                repository=None,
                create_pr=False,
                mode="interactive",
                initial_permission_mode="default",
                start_workflow=False,
            )
        except ValueError:
            raise exceptions.ValidationError("Failed to create sandbox task.")

        task_run_or_none = task.latest_run
        if not task_run_or_none:
            raise exceptions.ValidationError("Failed to create sandbox task run.")
        task_run = task_run_or_none

        # Stash the composed system prompt and the full, undeduped structured context on the Run
        # state before the workflow launches. RunState is extra="allow", so these well-known keys
        # are non-breaking (01_CONTEXT § 4.1, § 4.5).
        # Deliberate divergence: `description` carries the pruned (deduped) wrapped content sent to
        # the agent, while `state["attached_context"]` keeps the full undeduped list as a raw-audit copy.
        run_state = task_run.state or {}
        run_state["system_prompt"] = system_prompt
        run_state["attached_context"] = [item.model_dump(exclude_none=True) for item in attached_context]
        task_run.state = run_state
        task_run.save(update_fields=["state"])

        run_id = str(task_run.id)
        set_sandbox_mapping(conversation_id, str(task.id), run_id)

        conversation.sandbox_task_id = task.id
        conversation.sandbox_run_id = task_run.id
        conversation.save(update_fields=["sandbox_task_id", "sandbox_run_id"])

        # Force "full" MCP scopes to preserve Task.create_and_run's default — the workflow
        # entrypoint defaults to "read_only", which would silently strip the agent's write tools.
        execute_task_processing_workflow(
            task_id=str(task.id),
            run_id=run_id,
            team_id=task.team_id,
            user_id=user.pk,
            create_pr=False,
            posthog_mcp_scopes="full",
        )

        _seed_sandbox_stream(run_id)

        _emit_prompt_sent(
            team=team,
            user=user,
            conversation_id=conversation_id,
            attached_context=attached_context,
            just_created_run=True,
        )

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


def _persist_run_attached_context(task_run: TaskRun, undeduped_context: list[dict[str, Any]]) -> None:
    """Persist the full undeduped attached_context on an in-progress Run's state.

    The signal carries only the wrapped content + artifact ids, so the structured context is
    kept as a raw-audit copy on the Run state. The Run's Temporal workflow mutates ``state``
    concurrently (e.g. activities writing ``sandbox_url``), so use the locked atomic merge
    instead of an unlocked read-modify-write that would clobber keys written in parallel.
    """
    TaskRun.update_state_atomic(task_run.id, updates={"attached_context": undeduped_context})


def _emit_prompt_sent(
    *,
    team: Team,
    user: User,
    conversation_id: str,
    attached_context: list[AttachedContext],
    just_created_run: bool,
) -> None:
    """Emit the PROMPT_SENT analytics event for a sandbox turn.

    Runs in the synchronous HTTP request thread (not a Celery task), so direct
    ``posthoganalytics.capture`` is correct here.
    """
    try:
        posthoganalytics.capture(
            distinct_id=str(user.distinct_id),
            event=PROMPT_SENT_EVENT,
            properties={
                "conversation_id": conversation_id,
                "execution_type": "sandbox",
                "agent_runtime": "sandbox",
                "just_created_run": just_created_run,
                "has_attached_context": bool(attached_context),
                "attached_context_count": len(attached_context),
            },
            groups=groups(team=team),
        )
    except Exception as e:
        logger.warning("sandbox_prompt_sent_capture_failed", conversation_id=conversation_id, error=str(e))


def cancel_sandbox_run(task_run: TaskRun, user: User) -> str:
    """Cancel a sandbox Run by proxying a ``cancel`` command to the live agent server.

    Mirrors the non-``user_message`` branch of ``TaskRunViewSet.command`` (products/tasks
    /backend/api.py): the cancel/permission/close commands proxy *synchronously* to the agent
    server and require a live ``state.sandbox_url`` validated against the SSRF allowlist. Raises a
    DRF ``ValidationError``/``APIException`` so the conversation cancel @action surfaces a useful
    HTTP status. Returns the run status reported back by the agent server (typically ``cancelled``).
    """
    run_state = parse_run_state(task_run.state)

    if not run_state.sandbox_url:
        raise exceptions.ValidationError("No active sandbox for this task run.")

    if not TaskRunViewSet._is_valid_sandbox_url(run_state.sandbox_url):
        logger.warning("sandbox_cancel_blocked_invalid_url", run_id=str(task_run.id))
        raise exceptions.ValidationError("Invalid sandbox URL.")

    connection_token = create_sandbox_connection_token(
        task_run=task_run,
        user_id=user.pk,
        distinct_id=str(user.distinct_id),
    )

    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": "cancel", "params": {}}

    try:
        agent_response = TaskRunViewSet._proxy_command_to_agent_server(
            sandbox_url=run_state.sandbox_url,
            connection_token=connection_token,
            sandbox_connect_token=run_state.sandbox_connect_token,
            payload=payload,
        )
    except (http_requests.ConnectionError, http_requests.Timeout) as e:
        logger.warning("sandbox_cancel_agent_unreachable", run_id=str(task_run.id), error=str(e))
        raise exceptions.APIException("Agent server is not reachable.")
    except Exception as e:
        logger.exception("sandbox_cancel_proxy_failed", run_id=str(task_run.id), error=str(e))
        raise exceptions.APIException("Failed to send cancel command to agent server.")

    if not agent_response.ok:
        logger.warning("sandbox_cancel_agent_rejected", run_id=str(task_run.id), status=agent_response.status_code)
        raise exceptions.APIException("Agent server rejected the cancel command.")

    try:
        body = agent_response.json()
    except Exception:
        body = {}

    return str((body or {}).get("status") or TaskRun.Status.CANCELLED.value)


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
