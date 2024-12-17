import os
import json
import requests
import uuid
import sys
import time
import threading
import shutil  # noqa: F401
import re
import readline  # noqa: F401
import logging
import traceback  # noqa: F401
from typing import Any, Dict  # noqa: F401, UP035
from .config import API_KEY, API_ENDPOINT, MODEL
from .supportSidebarMax_system_prompt import get_system_prompt

try:
    import anthropic
    from flask import Flask, request, jsonify, session  # noqa: F401
    from flask_cors import CORS
except ImportError as e:
    print(f"Error importing required packages: {e}")  # noqa: T201
    print("Please ensure you have installed: anthropic flask flask-cors")  # noqa: T201
    sys.exit(1)

from .max_search_tool import max_search_tool


class ConversationHistory:
    def __init__(self):
        self.turns = []

    def add_turn_user(self, content):
        self.turns.append({"role": "user", "content": [{"type": "text", "text": content}]})

    def add_turn_assistant(self, content):
        if isinstance(content, list):
            self.turns.append({"role": "assistant", "content": content})
        else:
            self.turns.append({"role": "assistant", "content": [{"type": "text", "text": content}]})

    def get_turns(self):
        return self.turns


class RequestCounter:
    def __init__(self):
        self._lock = threading.Lock()
        self._count = 0

    def increment(self) -> int:
        with self._lock:
            self._count += 1
            return self._count


request_counter = RequestCounter()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

client = anthropic.Anthropic()

app = Flask(__name__)
CORS(app)
CORS(
    app,
    resources={
        r"/chat": {"origins": ["http://localhost:8000"], "methods": ["POST"], "allow_headers": ["Content-Type"]}
    },
)

conversation_histories = {}

search_log_handler = logging.StreamHandler()
search_log_handler.setLevel(logging.INFO)


def create_simulated_429_response():
    mock_response = requests.Response()
    mock_response.status_code = 429
    mock_response._content = json.dumps(
        {
            "content": "🫣 Uh-oh, I'm really popular today! I've hit my rate limit. I need to catch my breath, please try asking your question again after 30 seconds. 🦔"
        }
    ).encode()
    mock_response.headers["retry-after"] = "1"
    mock_response.headers["anthropic-ratelimit-requests-remaining"] = "0"
    mock_response.headers["anthropic-ratelimit-tokens-remaining"] = "0"
    return mock_response


def should_simulate_rate_limit(count: int) -> bool:
    """Determines if we should simulate a rate limit based on environment variable and request count."""
    simulate_enabled = os.getenv("SIMULATE_RATE_LIMIT", "false").lower() == "true"
    return simulate_enabled and count > 3


def track_cache_performance(response):
    """Track and log cache performance metrics."""
    if "usage" in response:
        usage = response["usage"]
        print(f"Cache creation tokens: {usage.get('cache_creation_input_tokens', 0)}")  # noqa: T201
        print(f"Cache read tokens: {usage.get('cache_read_input_tokens', 0)}")  # noqa: T201
        print(f"Total input tokens: {usage.get('input_tokens', 0)}")  # noqa: T201
        print(f"Total output tokens: {usage.get('output_tokens', 0)}")  # noqa: T201
    else:
        print("No usage information available in the response.")  # noqa: T201


def get_message_content(message):
    if not message or "content" not in message:
        return ""

    content = message["content"]
    if isinstance(content, list):
        for block in content:
            if block.get("type") == "text":
                return block.get("text", "")
            elif block.get("type") == "tool_use":
                return block.get("input", {}).get("query", "")
    elif isinstance(content, str):
        return content
    return ""


def send_message(system_prompt, messages, tools):
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "prompt-caching-2024-07-31",
        "content-type": "application/json",
    }
    data = {
        "model": MODEL,
        "max_tokens": 1024,
        "tools": tools,
        "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
    }

    try:
        logger.info("Sending request to Anthropic API.")
        logger.debug(f"Request headers: {headers}")
        logger.debug(f"Request payload: {json.dumps(data, indent=2)}")

        max_retries = 3
        retry_count = 0
        max_backoff = 32  # Maximum backoff in seconds

        while retry_count <= max_retries:
            # Make the request
            req_count = request_counter.increment()

            # Check if we should use the mock for testing - only check the most recent message
            current_message = get_message_content(messages[-1]) if messages else ""
            if "__500__" in current_message:
                response = mock_post(API_ENDPOINT, headers, data)
                logger.info(f"Using mock response for 500 error test (request #{req_count})")
            else:
                response = requests.post(API_ENDPOINT, headers=headers, json=data)

            rate_limits = {
                "requests_remaining": response.headers.get("anthropic-ratelimit-requests-remaining", "not provided"),
                "tokens_remaining": response.headers.get("anthropic-ratelimit-tokens-remaining", "not provided"),
                "retry_after": response.headers.get("retry-after", "not provided"),
            }
            logger.info(
                f"Rate limits - Requests remaining: {rate_limits['requests_remaining']}, "
                f"Tokens remaining: {rate_limits['tokens_remaining']}"
            )

            if response.status_code == 429:
                if retry_count < max_retries:
                    # Try to get retry_after value, fall back to exponential backoff
                    try:
                        retry_after = (
                            int(rate_limits["retry_after"]) if rate_limits["retry_after"] != "not provided" else None
                        )
                    except (ValueError, TypeError):
                        retry_after = None

                    if retry_after is None:
                        retry_after = min(2**retry_count, max_backoff)  # Exponential backoff with upper bound

                    logger.warning(
                        f"Rate limit exceeded. Attempt {retry_count + 1}/{max_retries}. "
                        f"Retrying in {retry_after} seconds..."
                    )
                    time.sleep(retry_after)
                    retry_count += 1
                    continue
                else:
                    logger.error("Max retries exceeded due to rate limiting")
                    return {
                        "content": "🫣 Uh-oh, I'm really popular today! I've hit my rate limit. I need to catch my breath, please try asking your question again after 30 seconds. 🦔",
                        "isRateLimited": True,
                    }

            if response.status_code in [500, 524, 529]:
                logger.info(f"Server error detected: {response.status_code}")
                error_message = (
                    "🫣 Uh-oh. I wasn't able to connect to the Anthropic API (my brain!) Please try sending your message again in about 1 minute?\n\n"
                    "If this message is still recurring after 5 or 10 minutes, there may be info about the trouble available at [status.anthropic.com](https://status.anthropic.com)."
                )

                logger.info(f"Injecting error message: {error_message}")
                return {"content": [{"type": "text", "text": error_message}], "isError": True}

            # For non-429 responses, ensure other error codes raise exceptions
            response.raise_for_status()

            # Parse and log the response
            response_data = response.json()
            logger.info("Received response from Anthropic API.")
            logger.debug(f"Response data: {json.dumps(response_data, indent=2)}")

            # Track cache performance
            track_cache_performance(response_data)

            return response_data

    except requests.RequestException as e:
        logger.error(f"Request to Anthropic API failed: {str(e)}", exc_info=True)
        raise

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON response from Anthropic API: {str(e)}", exc_info=True)
        raise

    except Exception as e:
        logger.error(f"Unexpected error in send_message: {str(e)}", exc_info=True)
        raise


def extract_reply(text):
    """Extract a reply enclosed in <reply> tags."""
    try:
        logger.info("Extracting reply from text.")
        if not isinstance(text, str):
            raise ValueError(f"Invalid input: Expected a string, got {type(text)}.")

        pattern = r"<reply>(.*?)</reply>"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            extracted_reply = match.group(1)
            logger.debug(f"Extracted reply: {extracted_reply}")
            return extracted_reply
        else:
            logger.info("No <reply> tags found in the text.")
            return None
    except Exception as e:  # noqa: F841
        logger.error("Error extracting reply.", exc_info=True)
        raise


def process_response(response, messages, system_prompt):
    try:
        if "content" in response:
            assistant_response = response["content"]
            logger.info("Processing response content.")

            if isinstance(assistant_response, list):
                # Keep all content blocks together in one message
                messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_response,  # The entire list of content blocks
                    }
                )

                # Handle tool use if present
                for content_block in assistant_response:
                    if content_block["type"] == "tool_use":
                        query = content_block["input"]["query"]
                        logger.info(f"Handling tool invocation with query: {query}")

                        # Perform search and log results
                        search_results = max_search_tool(query)
                        logger.debug(f"Search results: {search_results}")

                        if isinstance(search_results, str):
                            formatted_results_str = search_results
                        else:
                            formatted_results = []
                            for result in search_results:
                                for passage in result["relevant_passages"]:
                                    formatted_results.append(
                                        f"Text: {passage['text']}\n"
                                        f"Heading: {passage['heading']}\n"
                                        f"Source: {result['page_title']}\n"
                                        f"URL: {passage['url']}\n"
                                    )
                            formatted_results_str = "\n".join(formatted_results)

                        logger.debug(f"Formatted search results: {formatted_results_str}")

                        # Append tool result as a content block
                        messages.append(
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": content_block["id"],
                                        "content": formatted_results_str,
                                    }
                                ],
                            }
                        )

                        # Call send_message recursively and log errors
                        try:
                            next_response = send_message(system_prompt, messages, [max_search_tool_tool])
                            updated_messages = process_response(next_response, messages, system_prompt)
                            if updated_messages:
                                messages = updated_messages
                        except Exception as e:  # noqa: F841
                            logger.error("Error during recursive send_message call.", exc_info=True)
                            raise
                return messages
            else:
                # Handle string response (should we convert to content block?)
                messages.append({"role": "assistant", "content": [{"type": "text", "text": assistant_response}]})
                return messages
        else:
            logger.warning("No content found in response.")
            return messages
    except Exception as e:  # noqa: F841
        logger.error("Error processing response.", exc_info=True)
        raise


max_search_tool_tool = {
    "name": "max_search_tool",
    "description": (
        "Searches the PostHog documentation at https://posthog.com/docs, "
        "https://posthog.com/tutorials, to find information relevant to the "
        "user's question. The search query should be a question specific to using "
        "and configuring PostHog."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, in the form of a question, related to PostHog usage and configuration.",
            }
        },
        "cache_control": {"type": "ephemeral"},
        "required": ["query"],
    },
}


def validate_tool_input(input_data):
    """Validate the input for max_search_tool_tool."""
    try:
        if not isinstance(input_data, dict):
            raise ValueError("Input data must be a dictionary.")
        if "query" not in input_data or not input_data["query"].strip():
            raise ValueError("The 'query' field is required and cannot be empty.")
        logger.debug(f"Tool input validation passed: {input_data}")
    except Exception as e:
        logger.error(f"Tool input validation failed: {str(e)}", exc_info=True)
        raise


def format_response(response):
    if "content" in response:
        assistant_response = response["content"]
        if isinstance(assistant_response, list):
            formatted_response = "\n"
            for content_block in assistant_response:
                if content_block["type"] == "text":
                    formatted_response += content_block["text"] + "\n"
            return formatted_response.strip() + "\n"
        else:
            return "\n" + assistant_response + "\n"
    else:
        return "\n\nError: No response from Max.\n\n"


@app.route("/chat", methods=["POST"])
def chat():
    try:
        logger.info("Incoming request to /chat endpoint.")
        data = request.json
        if not data or "message" not in data:
            logger.warning("Invalid request: No 'message' provided.")
            return jsonify({"error": "No message provided"}), 400

        user_input = data["message"]
        logger.info(f"User input received: {user_input}")

        session_id = data.get("session_id", str(uuid.uuid4()))

        if session_id not in conversation_histories:
            conversation_histories[session_id] = ConversationHistory()

        history = conversation_histories[session_id]
        system_prompt = get_system_prompt()  # Get system prompt once at the start

        if not user_input.strip():
            history.add_turn_user("Hello!")
            logger.info("No user input. Sending default greeting.")
            result = send_message(system_prompt, history.get_turns(), [max_search_tool_tool])
            if "content" in result:
                logger.debug(f"Greeting response: {result['content']}")
                history.add_turn_assistant(result["content"])
                return jsonify({"content": result["content"]})

        history.add_turn_user(user_input)

        messages = history.get_turns()

        full_response = ""

        # Send message with full history
        result = send_message(system_prompt, messages, [max_search_tool_tool])
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

                result = send_message(system_prompt, history.get_turns(), [max_search_tool_tool])
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
        return jsonify({"content": full_response.strip(), "session_id": session_id})

    except requests.RequestException as e:
        logger.error(f"Request to Anthropic API failed: {str(e)}", exc_info=True)
        try:
            # Try to parse the error message as JSON in case it's our custom message
            error_content = json.loads(str(e))
            if "content" in error_content:
                return jsonify(error_content), 429
        except json.JSONDecodeError:
            pass
        # Fall back to generic error handling
        return jsonify({"error": str(e)}), 500


# Expose the chat function as chat_endpoint for Django to import
chat_endpoint = chat


def mock_post(url, headers, json_data):
    # Check if the message contains '__500__'
    if any("__500__" in msg["content"][0]["text"] for msg in json_data["messages"]):
        # Only return 500 error for the first request after seeing __500__
        if not hasattr(mock_post, "has_returned_500"):
            mock_post.has_returned_500 = True
            mock_response = requests.Response()
            mock_response.status_code = 500
            mock_response._content = bytes(
                '{"content": [{"type": "text", "text": "Mocked 500 error"}]}', encoding="utf-8"
            )
            return mock_response
        else:
            # Reset the flag and let the real API handle the response
            delattr(mock_post, "has_returned_500")
            return requests.post(url, headers=headers, json=json_data)

    # For all other requests, use the real API
    return requests.post(url, headers=headers, json=json_data)


if __name__ == "__main__":
    try:
        print("Starting Max's chat server on port 3000... 🦔")  # noqa: T201
        app.run(port=3000, debug=True)
    except KeyboardInterrupt:
        print("\nShutting down Max's chat server... 👋")  # noqa: T201
        sys.exit(0)
    except Exception as e:
        print(f"\n\n🔴 Oops! Something went wrong: {str(e)}\n")  # noqa: T201
        sys.exit(1)
