from typing import Any
from django.http import JsonResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from .sidebar_max_AI import (
    ConversationHistory,
    send_message,
    get_system_prompt,
    max_search_tool_tool,
    logger,
)
from .max_search_tool import max_search_tool

conversation_histories = {}


class MaxViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """
    ViewSet for Max, the PostHog Support AI Assistant.
    """

    scope_object = "query"  # Similar to other PostHog query endpoints

    @action(methods=["POST"], detail=False)
    def chat(self, request: Request, **kwargs: Any) -> Response:
        try:
            logger.info("Incoming request to chat endpoint.")
            data = request.data
            if not data or "message" not in data:
                logger.warning("Invalid request: No 'message' provided.")
                return JsonResponse({"error": "No message provided"}, status=400)

            user_input = data["message"]
            logger.info(f"User input received: {user_input}")

            session_id = request.session.session_key
            if not session_id:
                request.session.create()
                session_id = request.session.session_key

            if session_id not in conversation_histories:
                conversation_histories[session_id] = ConversationHistory()

            history = conversation_histories[session_id]

            if not user_input.strip():
                history.add_turn_user("Hello!")
                logger.info("No user input. Sending default greeting.")
                result = send_message(get_system_prompt(), history.get_turns(), [max_search_tool_tool])
                if "content" in result:
                    logger.debug(f"Greeting response: {result['content']}")
                    history.add_turn_assistant(result["content"])
                    return JsonResponse({"content": result["content"]})

            history.add_turn_user(user_input)

            messages = history.get_turns()

            full_response = ""

            # Send message with full history
            result = send_message(get_system_prompt(), messages, [max_search_tool_tool])
            logger.debug(f"Initial response from send_message: {result}")

            while result and "content" in result:
                if result.get("stop_reason") == "tool_use":
                    tool_use_block = result["content"][-1]
                    logger.info(f"Tool use requested: {tool_use_block}")

                    query = tool_use_block["input"]["query"]
                    search_results = max_search_tool(query)
                    logger.debug(f"Search results for query '{query}': {search_results}")

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

                    # Append tool result as a content block
                    messages.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_use_block["id"],
                                    "content": formatted_results,
                                }
                            ],
                        }
                    )

                    for block in result["content"]:
                        if block["type"] == "text":
                            full_response += block["text"] + "\n"

                    result = send_message(get_system_prompt(), history.get_turns(), [max_search_tool_tool])
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

            logger.info("Response successfully processed.")
            return JsonResponse({"content": full_response.strip(), "session_id": session_id})

        except Exception as e:
            logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
            return JsonResponse({"error": str(e)}, status=500)
