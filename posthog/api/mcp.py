"""
SSE Server Transport Module - Django REST Framework Version

This module implements a Server-Sent Events (SSE) transport layer for MCP servers
using Django REST Framework.

Example usage:
```
    # Add SseServerTransportViewSet to your urls.py
    router = DefaultRouter()
    router.register(r'sse', SseServerTransportViewSet, basename='sse')

    # In your urls.py, also add the message handling endpoint
    urlpatterns = [
        path('api/', include(router.urls)),
        # ... other URL patterns
    ]

    # Or use the run_with_app method to set up an application
    from django.urls import path
    from sse_server_transport import SseServerTransportViewSet

    urlpatterns = [
        # ... your other URL patterns
        path('', SseServerTransportViewSet.run_with_app()),
    ]
```

See SseServerTransportViewSet class documentation for more details.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

import anyio
import mcp.types as types
from anyio.streams.memory import MemoryObjectSendStream
from django.http import StreamingHttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from pydantic import ValidationError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

logger = logging.getLogger(__name__)


class McpViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    Django REST Framework ViewSet that implements a Server-Sent Events (SSE) transport for MCP.

    This ViewSet provides two endpoints:

    1. GET /sse/ - establishes an SSE connection for receiving server messages
    2. POST /sse/message/?session_id={session_id} - sends client messages to the server
       that link to a previously established SSE session
    """

    # Dictionary to store stream writers for each session
    _read_stream_writers: dict[UUID, MemoryObjectSendStream[types.JSONRPCMessage | Exception]] = {}

    @method_decorator(csrf_exempt)
    @action(detail=False, methods=["get"])
    def connect_sse(self, request: Request):
        """
        Establishes a Server-Sent Events (SSE) connection.

        This is an endpoint which handles GET requests and sets up a new SSE stream
        to send server messages to the client.
        """
        session_id = uuid4()
        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        # Store the writer stream for this session
        session_uri = f"/sse/message/?session_id={session_id.hex}"
        self._read_stream_writers[session_id] = read_stream_writer
        logger.debug(f"Created new session with ID: {session_id}")

        # Create a stream for SSE events
        sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream[dict[str, Any]](0)

        async def sse_writer():
            """Writes messages to the SSE stream"""
            logger.debug("Starting SSE writer")
            async with sse_stream_writer, write_stream_reader:
                # Send the endpoint URL to the client
                await sse_stream_writer.send({"event": "endpoint", "data": session_uri})
                logger.debug(f"Sent endpoint event: {session_uri}")

                # Forward messages from write_stream to the SSE stream
                async for message in write_stream_reader:
                    logger.debug(f"Sending message via SSE: {message}")
                    await sse_stream_writer.send(
                        {
                            "event": "message",
                            "data": message.model_dump_json(by_alias=True, exclude_none=True),
                        }
                    )

        async def event_stream():
            """Generator function that yields SSE events"""
            # Start the SSE writer task
            async with anyio.create_task_group() as tg:
                tg.start_soon(sse_writer)

                # Read from the SSE stream and yield events
                async with sse_stream_reader:
                    async for event in sse_stream_reader:
                        event_type = event.get("event", "message")
                        data = event.get("data", "")
                        yield f"event: {event_type}\ndata: {data}\n\n".encode()

        # Create a StreamingHttpResponse for the SSE connection
        response = StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

        return response

    @method_decorator(csrf_exempt)
    @action(detail=False, methods=["post"], url_path="message")
    def handle_post_message(self, request: Request):
        """
        Handles POST requests containing client messages.

        These messages should link to a previously established SSE session
        via the session_id query parameter.
        """
        logger.debug("Handling POST message")

        # Get and validate the session ID
        session_id_param = request.query_params.get("session_id")
        if session_id_param is None:
            logger.warning("Received request without session_id")
            return Response("session_id is required", status=status.HTTP_400_BAD_REQUEST)

        try:
            session_id = UUID(hex=session_id_param)
            logger.debug(f"Parsed session ID: {session_id}")
        except ValueError:
            logger.warning(f"Received invalid session ID: {session_id_param}")
            return Response("Invalid session ID", status=status.HTTP_400_BAD_REQUEST)

        # Get the writer for this session
        writer = self._read_stream_writers.get(session_id)
        if not writer:
            logger.warning(f"Could not find session for ID: {session_id}")
            return Response("Could not find session", status=status.HTTP_404_NOT_FOUND)

        # Parse and validate the message
        body = request.body
        logger.debug(f"Received JSON: {body}")

        try:
            message = types.JSONRPCMessage.model_validate_json(body)
            logger.debug(f"Validated client message: {message}")
        except ValidationError as err:
            logger.exception(f"Failed to parse message: {err}")
            # Send the error to the client via the SSE stream
            anyio.from_thread.run(writer.send, err)
            return Response("Could not parse message", status=status.HTTP_400_BAD_REQUEST)

        # Send the message to the client via the SSE stream
        anyio.from_thread.run(writer.send, message)
        return Response("Accepted", status=status.HTTP_202_ACCEPTED)
