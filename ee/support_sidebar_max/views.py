from typing import Any
from django.conf import settings
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
import threading
import time
import anthropic
import json
from datetime import datetime, UTC

from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated

from ee.support_sidebar_max.supportSidebarMax_system_prompt import get_system_prompt
from .sidebar_max_AI import ConversationHistory, max_search_tool_tool
from .max_search_tool import max_search_tool


# Configure logging
django_logger = logging.getLogger("django")
django_logger.setLevel(logging.INFO)

# Don't add the auth header here, the Anthropic Python SDK handles it
REQUIRED_HEADERS = {
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}


class MaxChatViewSet(viewsets.ViewSet):
    """
    ViewSet for Max Support Sidebar Chat Assistant.
    Handles chat interactions with proper message structure and tool use.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]

    CONVERSATION_TIMEOUT = 300  # 5 minutes in seconds
    conversation_histories: dict[str, ConversationHistory] = {}
    _cleanup_lock = threading.Lock()
    basename = "max"

    def list(self, request: Request, **kwargs: Any) -> Response:
        """List endpoint - not used but required by DRF"""
        return Response({"detail": "List operation not supported"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def retrieve(self, request: Request, pk=None, **kwargs: Any) -> Response:
        """Retrieve endpoint - not used but required by DRF"""
        return Response({"detail": "Retrieve operation not supported"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def create(self, request: Request, **kwargs: Any) -> Response:
        django_logger.info("✨🦔 Starting chat endpoint execution")
        try:
            # Initialize Anthropic client
            django_logger.info("✨🦔 Initializing Anthropic client")
            try:
                django_logger.debug(f"✨🦔 ANTHROPIC_API_KEY exists: {bool(settings.ANTHROPIC_API_KEY)}")
                client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
                django_logger.debug("✨🦔 Anthropic client initialized successfully")
            except Exception as e:
                django_logger.error(f"✨🦔 Error initializing Anthropic client: {str(e)}", exc_info=True)
                raise

            django_logger.info("✨🦔 Checking request data")
            django_logger.debug(f"✨🦔 Request data: {json.dumps(request.data, indent=2)}")
            django_logger.debug(f"✨🦔 Request content type: {request.content_type}")
            django_logger.debug(f"✨🦔 Request headers: {dict(request.headers)}")

            data = request.data
            if not data:
                django_logger.warning("✨🦔 Invalid request: Empty request body")
                return Response({"error": "Empty request body"}, status=status.HTTP_400_BAD_REQUEST)
            if "message" not in data:
                django_logger.warning(f"✨🦔 Invalid request: No 'message' in data. Keys present: {data.keys()}")
                return Response({"error": "No message provided"}, status=status.HTTP_400_BAD_REQUEST)

            user_input = data["message"]
            django_logger.info(f"✨🦔 User input received: {user_input}")

            # Use session_id from request if provided, otherwise use Django session
            session_id = data.get("session_id")
            if not session_id:
                try:
                    session_id = request.session.session_key
                    if not session_id:
                        request.session.create()
                        session_id = request.session.session_key
                        if not session_id:
                            raise ValueError("Failed to create session key")
                    django_logger.debug(f"✨🦔 Session initialized successfully: {session_id}")
                except Exception as e:
                    django_logger.error(f"✨🦔 Session creation failed: {str(e)}", exc_info=True)
                    return Response(
                        {"error": "Session initialization failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            django_logger.info("✨🦔 Getting conversation history")
            history = self._get_conversation(session_id)
            system_prompt = self._format_system_prompt(get_system_prompt())
            django_logger.debug(f"✨🦔 System prompt: {json.dumps(system_prompt, indent=2)}")

            if not user_input.strip():
                django_logger.info("✨🦔 Empty input, sending default greeting")
                history.add_turn_user("Hello!")
                result = self.send_message(client, [max_search_tool_tool], system_prompt, history.get_turns())
                if isinstance(result, Response):  # Error response
                    return result
                if "content" in result:
                    django_logger.debug(f"✨🦔 Greeting response: {result['content']}")
                    history.add_turn_assistant(result["content"])
                    return Response({"content": result["content"]})

            # Add user message with proper structure
            history.add_turn_user(user_input)
            messages = history.get_turns()
            django_logger.debug(f"✨🦔 Messages to send: {json.dumps(messages, indent=2)}")
            full_response = ""

            # Send message with full history
            django_logger.info("✨🦔 Sending initial message to Anthropic API")
            result = self.send_message(client, [max_search_tool_tool], system_prompt, messages)
            if isinstance(result, Response):  # Error response
                return result
            django_logger.debug(f"✨🦔 Initial response from send_message: {json.dumps(result, indent=2)}")

            while result and "content" in result:
                if result.get("stop_reason") == "tool_use":
                    django_logger.info("✨🦔 Processing tool use response")
                    # Handle tool use with dedicated method
                    response_part, tool_result = self._handle_tool_use(result, history)
                    full_response += response_part
                    messages.append(tool_result)

                    # Get next response after tool use
                    django_logger.info("✨🦔 Sending follow-up message after tool use")
                    result = self.send_message(client, [max_search_tool_tool], system_prompt, history.get_turns())
                    if isinstance(result, Response):  # Error response
                        return result
                else:
                    django_logger.info("✨🦔 Processing final response")
                    if isinstance(result["content"], list):
                        for block in result["content"]:
                            if block["type"] == "text":
                                full_response += block["text"] + "\n"
                        history.add_turn_assistant(result["content"])
                    else:
                        full_response += result["content"]
                        history.add_turn_assistant(result["content"])
                    break

            django_logger.info("✨🦔 Response successfully processed")
            django_logger.debug(
                f"✨🦔 Final response: {json.dumps({'content': full_response.strip(), 'session_id': session_id}, indent=2)}"
            )
            return Response({"content": full_response.strip(), "session_id": session_id})

        except Exception as e:
            django_logger.error(f"✨🦔 Error in chat endpoint: {str(e)}", exc_info=True)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(methods=["POST"], detail=False, url_path="chat", url_name="chat")
    def chat(self, request: Request, **kwargs: Any) -> Response:
        return self.create(request, **kwargs)

    def _get_headers(self) -> dict[str, str]:
        """Get headers with container hostname from settings"""
        headers = REQUIRED_HEADERS.copy()
        headers["container_hostname"] = settings.CONTAINER_HOSTNAME
        return headers

    def _cleanup_old_conversations(self):
        """Remove conversations older than CONVERSATION_TIMEOUT"""
        with self._cleanup_lock:
            current_time = time.time()
            expired = [
                session_id
                for session_id, history in self.conversation_histories.items()
                if (current_time - history.last_access) > self.CONVERSATION_TIMEOUT
            ]
            for session_id in expired:
                del self.conversation_histories[session_id]

    def _get_conversation(self, session_id: str) -> ConversationHistory:
        """Get or create conversation history with cleanup check"""
        self._cleanup_old_conversations()
        if session_id not in self.conversation_histories:
            self.conversation_histories[session_id] = ConversationHistory()
        history = self.conversation_histories[session_id]
        history.touch()  # Update last access time
        return history

    def _format_system_prompt(self, prompt: str) -> list:
        """Format system prompt with cache control."""
        return [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]

    def _format_user_message(self, content: str) -> dict:
        """Format user message with proper structure."""
        return {"role": "user", "content": [{"type": "text", "text": content}]}

    def _format_tool_result(self, tool_use_id: str, content: str) -> dict:
        """Format tool result with proper structure."""
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                }
            ],
        }

    def _handle_rate_limit(self, retry_after: int) -> Response:
        """Handle rate limit with DRF response."""
        return Response(
            {
                "error": "rate_limit_exceeded",
                "message": "🫣 Uh-oh, I'm really popular today! I've hit my rate limit. I need to catch my breath, please try asking your question again after 30 seconds. 🦔",
                "retry_after": retry_after,
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
        )

    def _handle_tool_use(self, result: dict[str, Any], history: ConversationHistory) -> tuple[str, dict[str, Any]]:
        """Handle tool use response from the API"""
        full_response = ""
        # Process text blocks that came before tool use
        for block in result["content"]:
            if block["type"] == "text":
                full_response += block["text"] + "\n"

        tool_use_block = result["content"][-1]  # Get the last tool use block
        django_logger.info(f"Tool use requested: {tool_use_block}")

        query = tool_use_block["input"]["query"]
        search_results = max_search_tool(query)
        django_logger.debug(f"Search results for query '{query}': {search_results}")

        formatted_results = "\n".join(
            [
                f"Text: {passage['text']}\nHeading: {passage['heading']}\n"
                f"Source: {result_item['page_title']}\nURL: {passage['url']}\n"
                for result_item in search_results
                for passage in result_item["relevant_passages"]
            ]
        )

        # Append assistant's response with content blocks
        history.add_turn_assistant(result["content"])

        # Return the formatted results and current response
        return full_response, self._format_tool_result(tool_use_block["id"], formatted_results)

    def send_message(self, client: anthropic.Anthropic, tools, system_prompt, messages):
        """Send message to Anthropic API with proper error handling"""
        try:
            django_logger.info("✨🦔 Preparing to send message to Anthropic API")
            try:
                headers = {}
                django_logger.debug("✨🦔 API headers prepared successfully")
            except Exception as e:
                django_logger.error(f"✨🦔 Error preparing API headers: {str(e)}", exc_info=True)
                raise

            # Use with_raw_response to get access to headers
            raw_response = client.messages.with_raw_response.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                tools=tools,
                system=system_prompt,
                messages=messages,
                extra_headers=headers,
            )

            # Get the actual message response
            message = raw_response.parse()
            django_logger.debug(f"✨🦔 Response from Anthropic API: {message}")

            # Log rate limit information if available
            try:
                # Log current capacity (for monitoring/debugging)
                django_logger.info(
                    f"✨🦔 API Capacity - "
                    f"Requests: {raw_response.headers.get('anthropic-ratelimit-requests-remaining', '?')}/{raw_response.headers.get('anthropic-ratelimit-requests-limit', '?')}, "
                    f"Input Tokens: {raw_response.headers.get('anthropic-ratelimit-input-tokens-remaining', '?')}/{raw_response.headers.get('anthropic-ratelimit-input-tokens-limit', '?')}, "
                    f"Output Tokens: {raw_response.headers.get('anthropic-ratelimit-output-tokens-remaining', '?')}/{raw_response.headers.get('anthropic-ratelimit-output-tokens-limit', '?')}"
                )
            except Exception as e:
                django_logger.warning(f"✨🦔 Unable to log capacity info: {str(e)}")

            # Log token usage and cache metrics
            if message.usage:
                input_tokens = getattr(message.usage, "input_tokens", 0)
                output_tokens = getattr(message.usage, "output_tokens", 0)
                cache_created = getattr(message.usage, "cache_creation_input_tokens", 0)
                cache_read = getattr(message.usage, "cache_read_input_tokens", 0)
                fresh_input = getattr(message.usage, "input_tokens", 0)

                django_logger.info(f"✨🦔 Request Usage - Input: {input_tokens}, Output: {output_tokens} tokens")
                if cache_created or cache_read:
                    django_logger.info(
                        f"✨🦔 Cache Stats - Created: {cache_created}, Read: {cache_read}, Fresh: {fresh_input}"
                    )

            # Extract the necessary fields from the Message object
            result = {
                "content": [block.dict() for block in message.content]
                if isinstance(message.content, list)
                else message.content,
                "stop_reason": message.stop_reason,
                "usage": message.usage.dict() if message.usage else None,
            }

            django_logger.debug(f"✨🦔 Processed API response: {result}")
            return result

        except anthropic.RateLimitError as e:
            try:
                # Get reset time from headers if available
                headers = e.response.headers if hasattr(e, "response") and hasattr(e.response, "headers") else {}

                # Try to get retry-after header first
                if "retry-after" in headers:
                    retry_seconds = int(headers["retry-after"])
                else:
                    # Calculate from reset timestamp
                    now = datetime.now(UTC)
                    reset_times = []

                    for header in headers:
                        if header.endswith("-reset"):
                            try:
                                reset_time = datetime.fromisoformat(headers[header].rstrip("Zs")).replace(tzinfo=UTC)
                                wait_seconds = max(0, int((reset_time - now).total_seconds()))
                                reset_times.append(wait_seconds)
                            except (ValueError, TypeError):
                                continue

                    retry_seconds = max(reset_times) if reset_times else 15

                django_logger.warning(f"✨🦔 Rate limit hit - waiting {retry_seconds} seconds before retry")
                return self._handle_rate_limit(retry_seconds)

            except Exception as header_error:
                django_logger.warning(f"✨🦔 Rate limit handling error: {str(header_error)}")
                return self._handle_rate_limit(15)  # Default to 15 seconds
        except Exception as e:
            django_logger.error(f"✨🦔 Request to Anthropic API failed: {str(e)}", exc_info=True)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
