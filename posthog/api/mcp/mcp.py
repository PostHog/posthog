import asyncio
import json
import logging
import time
from urllib.parse import quote
from uuid import UUID, uuid4

import anyio
import mcp.types as types
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from django.http import StreamingHttpResponse
from mistune import BaseRenderer
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.redis import get_client

from .server import mcp_server

logger = logging.getLogger(__name__)

# Redis keys and channels
MCP_SESSION_KEY_PREFIX = "mcp:session:"
MCP_MESSAGE_CHANNEL_PREFIX = "mcp:messages:"


class ServerSentEventRenderer(BaseRenderer):
    media_type = "text/event-stream"
    format = "txt"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class McpViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "mcp"
    _endpoint = "/api/projects/1/mcp/messages"

    def get_renderers(self):
        if self.action == "sse":
            return [ServerSentEventRenderer()]
        return super().get_renderers()

    @action(detail=False, methods=["get"], required_scopes=["mcp:write"])
    def sse(self, request: Request, parent_lookup_project_id):
        """
        Establishes a Server-Sent Events (SSE) connection.

        This is an endpoint which handles GET requests and sets up a new SSE stream
        to send server messages to the client.
        """
        session_id = uuid4()
        session_uri = f"{quote(self._endpoint)}?session_id={session_id.hex}"

        read_stream: MemoryObjectReceiveStream[types.JSONRPCMessage | Exception]
        read_stream_writer: MemoryObjectSendStream[types.JSONRPCMessage | Exception]

        write_stream: MemoryObjectSendStream[types.JSONRPCMessage]
        write_stream_reader: MemoryObjectReceiveStream[types.JSONRPCMessage]

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        # Store session in Redis
        redis_client = get_client()
        session_key = f"{MCP_SESSION_KEY_PREFIX}{session_id.hex}"
        session_data = json.dumps(
            {
                "created_at": time.time(),
            }
        )
        redis_client.set(session_key, session_data)
        # Set expiration for 24 hours
        redis_client.expire(session_key, 86400)

        async def subscriber():
            async with read_stream:
                pubsub = redis_client.pubsub()
                pubsub.subscribe(MCP_MESSAGE_CHANNEL_PREFIX + session_id.hex)

                while True:
                    message = pubsub.get_message()
                    if message and message["type"] == "message":
                        await read_stream.send(message["data"])

                    await asyncio.sleep(1)

        async def event_stream():
            async with anyio.create_task_group() as tg, write_stream_reader:
                tg.start_soon(mcp_server.run, read_stream, write_stream, mcp_server.create_initialization_options())
                tg.start_soon(subscriber)
                yield self._serialize_message({"event": "endpoint", "data": session_uri})
                async for message in write_stream_reader:
                    yield self._serialize_message(message)

        # Create a StreamingHttpResponse for the SSE connection
        return StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @action(detail=False, methods=["post"], url_path="messages", required_scopes=["mcp:write"])
    def handle_post_message(self, request: Request, parent_lookup_project_id):
        """
        Handles POST requests containing client messages.

        These messages should link to a previously established SSE session
        via the session_id query parameter.
        """
        logger.debug("Handling POST message")

        # Get and validate the session ID
        session_id_param = request.query_params.get("sessionId")
        if session_id_param is None:
            logger.warning("Received request without session_id")
            return Response("session_id is required", status=status.HTTP_400_BAD_REQUEST)

        try:
            session_id = UUID(hex=session_id_param)
            logger.debug(f"Parsed session ID: {session_id}")
        except ValueError:
            logger.warning(f"Received invalid session ID: {session_id_param}")
            return Response("Invalid session ID", status=status.HTTP_400_BAD_REQUEST)

        # Verify session exists in Redis
        redis_client = get_client()
        session_key = f"{MCP_SESSION_KEY_PREFIX}{session_id.hex}"
        if not redis_client.exists(session_key):
            logger.warning(f"Could not find session in Redis for ID: {session_id}")
            return Response("Could not find session", status=status.HTTP_404_NOT_FOUND)

        # Parse and validate the message
        body = request.body
        if isinstance(body, bytes):
            body_str = body.decode("utf-8")
            logger.debug(f"Received JSON: {body_str}")
        else:
            logger.debug(f"Received JSON: {body}")
            body_str = body

        try:
            message = types.JSONRPCMessage.model_validate_json(body_str)
            logger.debug(f"Validated client message: {message}")
        except ValidationError as err:
            logger.exception(f"Failed to parse message: {err}")
            # Handle error response and publish to Redis
            self._handle_message_error(session_id, err)
            return Response("Could not parse message", status=status.HTTP_400_BAD_REQUEST)

        # Publish the message to Redis channel
        channel_name = f"{MCP_MESSAGE_CHANNEL_PREFIX}{session_id.hex}"
        redis_client = get_client()

        # Serialize the message to JSON
        message_json = message.model_dump_json(by_alias=True, exclude_none=True)

        # Publish to Redis
        redis_client.publish(channel_name, message_json)
        logger.debug(f"Published message to Redis channel {channel_name}")

        return Response("Accepted", status=status.HTTP_202_ACCEPTED)

    def _serialize_message(self, message: dict) -> str:
        output = ""
        output += f"event: {message['event']}\n"
        return output + f"data: {json.dumps(message['data'])}\n\n"
