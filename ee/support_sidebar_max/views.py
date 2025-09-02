"""
ViewSet for Max Support Sidebar Chat Assistant.
"""

import asyncio
import logging
import builtins
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any, Optional

from django.conf import settings

import anthropic
from asgiref.sync import sync_to_async
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from ee.support_sidebar_max.prompt import get_system_prompt

from .max_search_tool import max_search_tool
from .sidebar_max_ai import ConversationHistory, RateLimitType, max_search_tool_tool

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

    CONVERSATION_TIMEOUT = 3600  # one hour
    MAX_BACKOFF = 40  # Maximum backoff in seconds to prevent gateway timeouts
    basename = "max"

    def _convert_headers(self, headers: MutableMapping[str, str]) -> dict[str, str]:
        """Convert MutableMapping headers to dict safely."""
        return dict(headers)

    def list(self, request: Request, **kwargs: Any) -> Response:
        """List endpoint - not used but required by DRF"""
        return Response({"detail": "List operation not supported"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def retrieve(self, request: Request, pk=None, **kwargs: Any) -> Response:
        """Retrieve endpoint - not used but required by DRF"""
        return Response({"detail": "Retrieve operation not supported"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    async def async_send_message(self, client: anthropic.Anthropic, tools, system_prompt, messages):
        """Async wrapper for send_message"""

        @sync_to_async(thread_sensitive=False)
        def _send_message():
            return self.send_message(client, tools, system_prompt, messages)

        return await _send_message()

    async def async_create(self, request: Request, **kwargs: Any) -> Response:
        """Async version of create method"""
        try:
            # Check if we're currently rate limited
            is_rate_limited, retry_after, limit_type = ConversationHistory.check_rate_limits()
            if is_rate_limited:
                return self._handle_rate_limit(retry_after, limit_type)

            # Initialize Anthropic client (non-blocking)
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

            data = request.data
            if not data or "message" not in data:
                return Response({"error": "No message provided"}, status=status.HTTP_400_BAD_REQUEST)

            user_input = data["message"]
            session_id = data.get("session_id") or request.session.session_key
            if not session_id:
                request.session.create()
                session_id = request.session.session_key
            assert isinstance(session_id, str)  # Type narrowing for mypy

            history = ConversationHistory.get_from_cache(session_id)
            system_prompt = self._format_system_prompt(get_system_prompt())

            if not user_input.strip():
                history.add_turn_user("Hello!")
                result = await self.async_send_message(
                    client, [max_search_tool_tool], system_prompt, history.get_turns()
                )
                if isinstance(result, Response):  # Error response
                    return result
                if "content" in result:
                    history.add_turn_assistant(result["content"])
                    history.save_to_cache(session_id, timeout=self.CONVERSATION_TIMEOUT)
                    return Response({"content": result["content"]})

            history.add_turn_user(user_input)
            messages = history.get_turns()
            full_response = ""

            result = await self.async_send_message(client, [max_search_tool_tool], system_prompt, messages)
            if isinstance(result, Response):  # Error response
                return result

            while result and "content" in result:
                if result.get("stop_reason") == "tool_use":
                    response_part, tool_result = self._handle_tool_use(result, history)
                    full_response += response_part
                    messages.append(tool_result)

                    result = await self.async_send_message(
                        client, [max_search_tool_tool], system_prompt, history.get_turns()
                    )
                    if isinstance(result, Response):  # Error response
                        return result
                else:
                    if isinstance(result["content"], list):
                        for block in result["content"]:
                            if block["type"] == "text":
                                full_response += block["text"] + "\n"
                        history.add_turn_assistant(result["content"])
                    else:
                        full_response += result["content"]
                        history.add_turn_assistant(result["content"])
                    break

            history.save_to_cache(session_id, timeout=self.CONVERSATION_TIMEOUT)
            return Response({"content": full_response.strip(), "session_id": session_id})

        except Exception as e:
            django_logger.error(f"✨🦔 Error in chat endpoint: {str(e)}", exc_info=True)
            return Response(
                {"error": "An unexpected error occurred. Please try again later."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def create(self, request: Request, **kwargs: Any) -> Response:
        """Synchronous wrapper for async_create"""
        return asyncio.run(self.async_create(request, **kwargs))

    @action(methods=["POST"], detail=False, url_path="chat", url_name="chat")
    def chat(self, request: Request, **kwargs: Any) -> Response:
        return self.create(request, **kwargs)

    def _get_headers(self) -> dict[str, str]:
        """Get headers with container hostname from settings"""
        headers = REQUIRED_HEADERS.copy()
        headers["container_hostname"] = settings.CONTAINER_HOSTNAME
        return headers

    def _format_system_prompt(self, prompt: str) -> builtins.list[dict[str, Any]]:
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

    def _handle_rate_limit(self, retry_after: Optional[int], limit_type: Optional[RateLimitType] = None) -> Response:
        """Handle rate limit with DRF response."""
        capped_retry = min(retry_after if retry_after is not None else self.MAX_BACKOFF, self.MAX_BACKOFF)
        limit_message = f" ({limit_type.replace('_', ' ')})" if limit_type else ""
        return Response(
            {
                "error": "rate_limit_exceeded",
                "message": f"🫣 Uh-oh, I'm really popular today, we've been rate-limited{limit_message}. I just need to catch my breath. Hang on, I'll repeat your question for you and resume searching in less than a minute...",
                "retry_after": capped_retry,
                "limit_type": limit_type,
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(capped_retry)},
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
                headers: dict[str, str] = {}
                django_logger.debug("✨🦔 API headers prepared successfully")
            except Exception as e:
                django_logger.error(f"✨🦔 Error preparing API headers: {str(e)}", exc_info=True)
                raise

            # Check token count before sending
            count = client.messages.count_tokens(
                messages=messages,
                model="claude-3-5-sonnet-20241022",
                system=system_prompt,
                tools=tools,  # Include same tools as in create()
            )

            # Pre-check if we have enough tokens
            if not ConversationHistory.consume_tokens("input_tokens", count.input_tokens):
                return self._handle_rate_limit(45, "input_tokens")

            if count.input_tokens > 190000:  # Safe buffer below 200k limit
                messages = [messages[0], messages[-1]]  # Keep first and last messages

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

            # Update rate limits from headers
            try:
                response_headers = self._convert_headers(raw_response.headers)
                ConversationHistory.update_rate_limits(response_headers)
                django_logger.info(
                    f"✨🦔 API Capacity - "
                    f"Requests: {response_headers.get('anthropic-ratelimit-requests-remaining', '?')}/{response_headers.get('anthropic-ratelimit-requests-limit', '?')}, "
                    f"Input Tokens: {response_headers.get('anthropic-ratelimit-input-tokens-remaining', '?')}/{response_headers.get('anthropic-ratelimit-input-tokens-limit', '?')}, "
                    f"Output Tokens: {response_headers.get('anthropic-ratelimit-output-tokens-remaining', '?')}/{response_headers.get('anthropic-ratelimit-output-tokens-limit', '?')}"
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

                # Consume output tokens
                if not ConversationHistory.consume_tokens("output_tokens", output_tokens):
                    return self._handle_rate_limit(45, "output_tokens")

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
                raw_headers = e.response.headers if hasattr(e, "response") and hasattr(e.response, "headers") else {}
                headers = self._convert_headers(raw_headers) if raw_headers else {}

                # Try to get retry-after header first
                if "retry-after" in headers:
                    retry_seconds = min(int(headers["retry-after"]), self.MAX_BACKOFF)
                else:
                    # Calculate from reset timestamp
                    now = datetime.now(UTC)
                    reset_times = []

                    for header in headers:
                        if header.endswith("-reset"):
                            try:
                                reset_time = datetime.fromisoformat(headers[header].rstrip("Zs")).replace(tzinfo=UTC)
                                wait_seconds = max(0, int((reset_time - now).total_seconds()))
                                reset_times.append(min(wait_seconds, self.MAX_BACKOFF))
                            except (ValueError, TypeError):
                                continue

                    retry_seconds = min(max(reset_times) if reset_times else self.MAX_BACKOFF, self.MAX_BACKOFF)

                # Determine which limit was hit from headers
                limit_type: Optional[RateLimitType] = None
                for key in headers:
                    if key.endswith("-remaining"):
                        if headers[key] == "0":
                            extracted_type = key.replace("anthropic-ratelimit-", "").replace("-remaining", "")
                            if extracted_type in ("requests", "input_tokens", "output_tokens"):
                                limit_type = extracted_type  # type: ignore # mypy doesn't understand the literal check
                            break

                django_logger.warning(f"✨🦔 Rate limit hit - waiting {retry_seconds} seconds before retry")
                return self._handle_rate_limit(retry_seconds, limit_type)

            except Exception as header_error:
                django_logger.warning(f"✨🦔 Rate limit handling error: {str(header_error)}")
                return self._handle_rate_limit(self.MAX_BACKOFF)  # Default to MAX_BACKOFF
        except Exception as e:
            django_logger.error(f"✨🦔 Request to Anthropic API failed: {str(e)}", exc_info=True)
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
