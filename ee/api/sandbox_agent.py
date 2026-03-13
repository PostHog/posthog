"""
External API endpoint for running sandbox AI agents.

Used by the CDP/Cyclotron executor (Hog templates) to run AI agents as workflow actions
and can be opened to third-party developers in the future.

Authentication: Bearer token (team api_token) in the Authorization header.
DRF authentication is disabled (authentication_classes = [], permission_classes = [AllowAny])
because the endpoint authenticates via team api_token, not user sessions or personal API keys.
"""

import json
import time

import structlog
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.models import OrganizationMembership, Team

from products.tasks.backend.models import TaskRun

from ee.hogai.sandbox_agent import SandboxAgentService

logger = structlog.get_logger(__name__)

AGENT_POLL_INTERVAL_SECONDS = 5
AGENT_MAX_WAIT_SECONDS = 600  # 10 minutes

# ACP notification methods we extract readable messages from
_TOOL_CALL_METHOD = "session/update"


_MAX_LOG_TEXT_LEN = 500


def _extract_text_from_content(content: object) -> str:
    """Extract text from an ACP ContentBlock or list of ContentBlocks."""
    if isinstance(content, dict):
        return str(content.get("text") or content.get("thinking") or "")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                t = block.get("text") or block.get("thinking") or ""
                if t:
                    parts.append(str(t))
        return "\n".join(parts)
    return ""


def _format_tool_input(tool_name: str, raw_input: object) -> str:
    """Format tool call input parameters into a readable summary."""
    if not isinstance(raw_input, dict):
        return ""
    if tool_name == "Bash":
        return raw_input.get("command", "")
    if tool_name in ("Read", "Grep", "Glob"):
        return raw_input.get("file_path") or raw_input.get("pattern") or raw_input.get("path") or ""
    if tool_name in ("Write", "Edit"):
        return raw_input.get("file_path", "")
    if tool_name == "Agent":
        return raw_input.get("prompt", "")[:200]
    # Generic: dump compact JSON
    try:
        return json.dumps(raw_input, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""


def _format_tool_output(tool_name: str, raw_output: object) -> str:
    """Format tool call output into a readable summary."""
    if isinstance(raw_output, str):
        return raw_output
    if isinstance(raw_output, list):
        # Content blocks from tool result
        parts = []
        for block in raw_output:
            if isinstance(block, dict):
                t = block.get("text", "")
                if t:
                    parts.append(str(t))
        return "\n".join(parts)
    if isinstance(raw_output, dict):
        try:
            return json.dumps(raw_output, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(raw_output)
    return ""


def _extract_agent_logs(task_run) -> list[str]:
    """Extract human-readable log messages from a TaskRun's stored ACP log.

    Reads the JSONL log from S3 and picks out agent thinking, text responses,
    and tool calls with their parameters and results.
    Returns a list of short summary strings suitable for display in the workflow test panel.
    """
    from posthog.storage import object_storage

    try:
        raw = object_storage.read(task_run.log_url, missing_ok=True)
    except Exception:
        return []

    if not raw:
        return []

    messages: list[str] = []
    # Accumulate streamed chunks by type before emitting
    thought_buffer: list[str] = []
    message_buffer: list[str] = []
    # Track tool calls we've already logged (avoid duplicates between tool_call and tool_call_update)
    seen_tool_calls: set[str] = set()

    def flush_thought():
        text = "".join(thought_buffer).strip()
        if text:
            messages.append(f"Thinking: {text[:_MAX_LOG_TEXT_LEN]}")
        thought_buffer.clear()

    def flush_message():
        text = "".join(message_buffer).strip()
        if text:
            messages.append(f"Agent: {text[:_MAX_LOG_TEXT_LEN]}")
        message_buffer.clear()

    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        notification = entry.get("notification") if isinstance(entry, dict) else None
        if not isinstance(notification, dict):
            continue

        method = notification.get("method", "")
        params = notification.get("params", {})

        if method == "_posthog/console":
            level = params.get("level", "info")
            msg = params.get("message", "")
            if msg:
                flush_thought()
                flush_message()
                messages.append(f"[{level}] {msg}")
            continue

        if method != _TOOL_CALL_METHOD:
            continue

        update = params.get("update") or params
        session_update = update.get("sessionUpdate")

        # Agent thinking
        if session_update == "agent_thought_chunk":
            # Flush any pending text message before thinking
            flush_message()
            text = _extract_text_from_content(update.get("content"))
            if text:
                thought_buffer.append(text)
            continue

        # Agent text response (complete or chunk)
        if session_update in ("agent_message", "agent_message_chunk"):
            # Flush any pending thinking before text
            flush_thought()
            text = _extract_text_from_content(update.get("content"))
            if text:
                message_buffer.append(text)
            continue

        # Tool call start — log the invocation with parameters
        if session_update == "tool_call":
            flush_thought()
            flush_message()
            tool_call_id = update.get("toolCallId", "")
            meta = (update.get("_meta") or {}).get("claudeCode", {})
            tool_name = meta.get("toolName") or update.get("title", "unknown")
            raw_input = update.get("rawInput") or meta.get("toolInput")
            input_summary = _format_tool_input(tool_name, raw_input)
            if input_summary:
                messages.append(f"Tool: {tool_name} — {input_summary[:_MAX_LOG_TEXT_LEN]}")
            else:
                messages.append(f"Tool: {tool_name}")
            seen_tool_calls.add(tool_call_id)
            continue

        # Tool call update — log completion with output
        if session_update == "tool_call_update":
            tool_call_id = update.get("toolCallId", "")
            tool_status = update.get("status")
            meta = (update.get("_meta") or {}).get("claudeCode", {})
            tool_name = meta.get("toolName") or ""

            # If we haven't seen the initial tool_call for this ID, log the invocation
            if tool_call_id and tool_call_id not in seen_tool_calls:
                raw_input = update.get("rawInput") or meta.get("toolInput")
                if tool_name and raw_input:
                    flush_thought()
                    flush_message()
                    input_summary = _format_tool_input(tool_name, raw_input)
                    if input_summary:
                        messages.append(f"Tool: {tool_name} — {input_summary[:_MAX_LOG_TEXT_LEN]}")
                    else:
                        messages.append(f"Tool: {tool_name}")
                    seen_tool_calls.add(tool_call_id)

            # Log tool result on completion/failure
            if tool_status in ("completed", "failed"):
                raw_output = update.get("rawOutput") or meta.get("toolResponse")
                if raw_output:
                    output_text = _format_tool_output(tool_name, raw_output)
                    if output_text:
                        status_label = "Result" if tool_status == "completed" else "Error"
                        messages.append(f"  {status_label}: {output_text[:_MAX_LOG_TEXT_LEN]}")
            continue

    # Flush any remaining buffers
    flush_thought()
    flush_message()

    return messages


class _SandboxAgentThrottle(SimpleRateThrottle):
    """Rate limit by Bearer token (team api_token)."""

    def get_cache_key(self, request, view):
        auth_header = request.headers.get("Authorization", "")
        ident = auth_header[7:].strip() if auth_header.startswith("Bearer ") else "anonymous"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class SandboxAgentBurstThrottle(_SandboxAgentThrottle):
    scope = "sandbox_agent_burst"
    rate = "30/minute"


class SandboxAgentSustainedThrottle(_SandboxAgentThrottle):
    scope = "sandbox_agent_sustained"
    rate = "300/hour"


def _authenticate_team(request: Request) -> tuple[Team, None] | tuple[None, Response]:
    """Extract Bearer token from Authorization header and resolve team."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, Response({"error": "Missing or invalid Authorization header"}, status=status.HTTP_401_UNAUTHORIZED)

    api_key = auth_header[7:].strip()
    if not api_key:
        return None, Response({"error": "Empty API key"}, status=status.HTTP_401_UNAUTHORIZED)

    team = Team.objects.get_team_from_cache_or_token(api_key)
    if team is None:
        return None, Response({"error": "Invalid API key"}, status=status.HTTP_401_UNAUTHORIZED)

    return team, None


class SandboxAgentRunSerializer(serializers.Serializer):
    message = serializers.CharField(required=True)
    repository = serializers.CharField(required=False, allow_null=True, default=None)
    output_schema = serializers.JSONField(required=False, allow_null=True, default=None)


class SandboxAgentView(APIView):
    """
    POST /agent/run — Spawn a sandbox AI agent and block until it completes.

    Authenticated via Bearer token (team api_token) in Authorization header.

    Spawns the agent and polls the TaskRun status server-side, returning only
    when the agent finishes (or the wait times out). Designed to be called as
    a single async step from the Hog VM / Cyclotron executor.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [SandboxAgentBurstThrottle, SandboxAgentSustainedThrottle]

    def post(self, request: Request) -> Response:
        team, error = _authenticate_team(request)
        if error or team is None:
            return error or Response({"error": "Authentication failed"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = SandboxAgentRunSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        message = serializer.validated_data["message"]
        repository = serializer.validated_data.get("repository")
        output_schema = serializer.validated_data.get("output_schema")

        user = (
            team.organization.members.filter(
                organization_membership__level__gte=OrganizationMembership.Level.ADMIN,
            )
            .order_by("organization_membership__joined_at")
            .first()
        )
        if not user:
            return Response(
                {"error": "No admin user found for this team's organization"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = SandboxAgentService.spawn_sandbox_task(
                team=team,
                user=user,
                title=f"Workflow agent: {message[:100]}",
                description=message,
                origin_product="user_created",
                repository=repository,
                create_pr=False,
                output_schema=output_schema,
            )
        except Exception as e:
            logger.exception("Failed to spawn sandbox task", error=e, team_id=team.id)
            return Response(
                {"error": "Failed to spawn agent"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        run_id = str(result.run_id)
        deadline = time.monotonic() + AGENT_MAX_WAIT_SECONDS

        while time.monotonic() < deadline:
            time.sleep(AGENT_POLL_INTERVAL_SECONDS)

            try:
                task_run = TaskRun.objects.get(id=run_id, team_id=team.id)
            except TaskRun.DoesNotExist:
                return Response({"error": "Run not found"}, status=status.HTTP_404_NOT_FOUND)

            if task_run.status in (TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS):
                continue

            if task_run.status == TaskRun.Status.COMPLETED:
                agent_logs = _extract_agent_logs(task_run)
                return Response(
                    {
                        "status": "completed",
                        "output": task_run.output,
                        "logs": agent_logs,
                    }
                )

            return Response(
                {
                    "status": "failed",
                    "error": task_run.error_message or "Agent failed",
                }
            )

        return Response(
            {"status": "failed", "error": "Agent timed out"},
            status=status.HTTP_504_GATEWAY_TIMEOUT,
        )
