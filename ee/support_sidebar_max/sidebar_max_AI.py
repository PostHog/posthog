import time
import shutil  # noqa: F401
import readline  # noqa: F401
import logging
import traceback  # noqa: F401
from typing import Any, Dict  # noqa: F401, UP035

# TODO: Flask imports preserved for reference during migration to Django views
# try:
#     import anthropic
#     from flask import Flask, request, jsonify, session  # noqa: F401
#     from flask_cors import CORS
# except ImportError as e:
#     print(f"Error importing required packages: {e}")  # noqa: T201
#     print("Please ensure you have installed: anthropic flask flask-cors")  # noqa: T201
#     sys.exit(1)


class ConversationHistory:
    def __init__(self):
        self.turns = []
        self.last_access = time.time()  # Add timestamp

    def touch(self):
        """Update last access time"""
        self.last_access = time.time()

    def add_turn_user(self, content):
        self.touch()  # Update timestamp on activity
        self.turns.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},  # User messages are stable for caching
                    }
                ],
            }
        )

    def add_turn_assistant(self, content):
        self.touch()  # Update timestamp on activity
        if isinstance(content, list):
            # Content is already properly structured
            self.turns.append({"role": "assistant", "content": content})
        else:
            # Add cache control for simple text responses
            self.turns.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},  # Assistant responses are stable for caching
                        }
                    ],
                }
            )

    def get_turns(self):
        self.touch()  # Update timestamp on activity
        return self.turns


# TODO: Classes preserved for reference - functionality moved to Django ViewSet
# class RequestCounter:
#     def __init__(self):
#         self._lock = threading.Lock()
#         self._count = 0
#
#     def increment(self) -> int:
#         with self._lock:
#             self._count += 1
#             return self._count
#
#
# request_counter = RequestCounter()

# Active logging configuration used by ViewSet
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# TODO: Flask app configuration preserved for reference
# app = Flask(__name__)
# CORS(app)
# CORS(
#     app,
#     resources={
#         r"/api/projects/*/max/chat/": {
#             "origins": ["http://localhost:8000"],
#             "methods": ["POST"],
#             "allow_headers": ["Content-Type"],
#         }
#     },
# )


# TODO: Classes preserved for reference - functionality moved to Django ViewSet
# class ConversationManager:
#     def __init__(self):
#         self.histories = {}
#
#     def get_history(self, session_id: str) -> ConversationHistory:
#         if session_id not in self.histories:
#             self.histories[session_id] = ConversationHistory()
#         return self.histories[session_id]
#
#
# class CachePerformanceLogger:
#     def __init__(self):
#         self.logger = logging.getLogger("ee.support_sidebar_max.cache")
#
#     def log_metrics(self, response):
#         if not response.get("usage"):
#             return
#
#         usage = response["usage"]
#         cache_read = usage.get("cache_read_input_tokens", 0)
#         cache_creation = usage.get("cache_creation_input_tokens", 0)
#
#         # Log at INFO level for significant cache misses
#         if cache_creation > 1000:
#             self.logger.info(f"Large cache miss: {cache_creation} creation tokens")
#         else:
#             self.logger.debug(
#                 f"Cache metrics - Read: {cache_read}, Creation: {cache_creation}, "
#                 f"Total input: {usage.get('input_tokens', 0)}"
#             )
#
#
# conversation_manager = ConversationManager()
# cache_logger = CachePerformanceLogger()


# TODO: Functions preserved for reference - functionality moved to Django ViewSet
# def create_simulated_429_response():
#     mock_response = requests.Response()
#     mock_response.status_code = 429
#     mock_response._content = json.dumps(
#         {
#             "content": "🫣 Uh-oh, I'm really popular today! I've hit my rate limit. I need to catch my breath, please try asking your question again after 30 seconds. 🦔"
#         }
#     ).encode()
#     mock_response.headers["retry-after"] = "1"
#     mock_response.headers["anthropic-ratelimit-requests-remaining"] = "0"
#     mock_response.headers["anthropic-ratelimit-tokens-remaining"] = "0"
#     return mock_response
#
#
# def should_simulate_rate_limit(count: int) -> bool:
#     """Determines if we should simulate a rate limit based on environment variable and request count."""
#     simulate_enabled = os.getenv("SIMULATE_RATE_LIMIT", "false").lower() == "true"
#     return simulate_enabled and count > 3
#
#
# def track_cache_performance(response):
#     """Track and log cache performance metrics."""
#     if "usage" in response:
#         usage = response["usage"]
#         print(f"Cache creation tokens: {usage.get('cache_creation_input_tokens', 0)}")  # noqa: T201
#         print(f"Cache read tokens: {usage.get('cache_read_input_tokens', 0)}")  # noqa: T201
#         print(f"Total input tokens: {usage.get('input_tokens', 0)}")  # noqa: T201
#         print(f"Total output tokens: {usage.get('output_tokens', 0)}")  # noqa: T201
#     else:
#         print("No usage information available in the response.")  # noqa: T201


# TODO: Functions preserved for reference - functionality moved to Django ViewSet
# def get_message_content(message):
#     if not message or "content" not in message:
#         return ""
#
#     content = message["content"]
#     if isinstance(content, list):
#         for block in content:
#             if block.get("type") == "text":
#                 return block.get("text", "")
#             elif block.get("type") == "tool_use":
#                 return block.get("input", {}).get("query", "")
#     elif isinstance(content, str):
#         return content
#     return ""
#
#
# def extract_reply(text):
#     """Extract a reply enclosed in <reply> tags."""
#     try:
#         logger.info("Extracting reply from text.")
#         if not isinstance(text, str):
#             raise ValueError(f"Invalid input: Expected a string, got {type(text)}.")
#
#         pattern = r"<reply>(.*?)</reply>"
#         match = re.search(pattern, text, re.DOTALL)
#         if match:
#             extracted_reply = match.group(1)
#             logger.debug(f"Extracted reply: {extracted_reply}")
#             return extracted_reply
#         else:
#             logger.info("No <reply> tags found in the text.")
#             return None
#     except Exception as e:  # noqa: F841
#         logger.error("Error extracting reply.", exc_info=True)
#         raise


# Active tool definition used by ViewSet
max_search_tool_tool = {
    "name": "max_search_tool",
    "description": (
        "Searches the PostHog documentation at https://posthog.com/docs, "
        "https://posthog.com/tutorials, to find information relevant to the "
        "user's question. The search query should be a question specific to using "
        "and configuring PostHog."
    ),
    "cache_control": {"type": "ephemeral"},
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, in the form of a question, related to PostHog usage and configuration.",
            }
        },
        "required": ["query"],
    },
}


# TODO: Functions preserved for reference - functionality moved to Django ViewSet
# def validate_tool_input(input_data):
#     """Validate the input for max_search_tool_tool."""
#     try:
#         if not isinstance(input_data, dict):
#             raise ValueError("Input data must be a dictionary.")
#         if "query" not in input_data or not input_data["query"].strip():
#             raise ValueError("The 'query' field is required and cannot be empty.")
#         logger.debug(f"Tool input validation passed: {input_data}")
#     except Exception as e:
#         logger.error(f"Tool input validation failed: {str(e)}", exc_info=True)
#         raise
#
#
# def format_response(response):
#     if "content" in response:
#         assistant_response = response["content"]
#         if isinstance(assistant_response, list):
#             formatted_response = "\n"
#             for content_block in assistant_response:
#                 if content_block["type"] == "text":
#                     formatted_response += content_block["text"] + "\n"
#             return formatted_response.strip() + "\n"
#         else:
#             return "\n" + assistant_response + "\n"
#     else:
#         return "\n\nError: No response from Max.\n\n"


# TODO: Flask route preserved for reference - functionality moved to Django ViewSet
# @app.route("/api/projects/<project_id>/max/chat/", methods=["POST"])
# def chat(project_id=None):
#     try:
#         logger.info("Incoming request to chat endpoint.")
#         data = request.json
#         if not data or "message" not in data:
#             logger.warning("Invalid request: No 'message' provided.")
#             return jsonify({"error": "No message provided"}), 400
#
#         user_input = data["message"]
#         logger.info(f"User input received: {user_input}")
#
#         session_id = data.get("session_id", str(uuid.uuid4()))
#         history = conversation_manager.get_history(session_id)
#         system_prompt = get_system_prompt()
#
#         if not user_input.strip():
#             history.add_turn_user("Hello!")
#             logger.info("No user input. Sending default greeting.")
#             result = send_message(system_prompt, history.get_turns(), [max_search_tool_tool])
#             if "content" in result:
#                 logger.debug(f"Greeting response: {result['content']}")
#                 history.add_turn_assistant(result["content"])
#                 cache_logger.log_metrics(result)
#                 return jsonify({"content": result["content"]})
#
#         history.add_turn_user(user_input)
#         messages = history.get_turns()
#         result = send_message(system_prompt, messages, [max_search_tool_tool])
#         cache_logger.log_metrics(result)
#
#         full_response = ""
#
#         # Send message with full history
#         result = send_message(system_prompt, messages, [max_search_tool_tool])
#         logger.debug(f"Initial response from send_message: {result}")
#
#         while result and "content" in result:
#             if result.get("stop_reason") == "tool_use":
#                 tool_use_block = result["content"][-1]
#                 logger.info(f"Tool use requested: {tool_use_block}")
#
#                 query = tool_use_block["input"]["query"]
#                 search_results = max_search_tool(query)
#                 logger.debug(f"Search results for query '{query}': {search_results}")
#
#                 formatted_results = "\n".join(
#                     [
#                         f"Text: {passage['text']}\nHeading: {passage['heading']}\n"
#                         f"Source: {result_item['page_title']}\nURL: {passage['url']}\n"
#                         for result_item in search_results
#                         for passage in result_item["relevant_passages"]
#                     ]
#                 )
#
#                 # Append assistant's response with content blocks
#                 history.add_turn_assistant(result["content"])
#
#                 # Append tool result as a content block
#                 messages.append(
#                     {
#                         "role": "user",
#                         "content": [
#                             {
#                                 "type": "tool_result",
#                                 "tool_use_id": tool_use_block["id"],
#                                 "content": formatted_results,
#                             }
#                         ],
#                     }
#                 )
#
#                 for block in result["content"]:
#                     if block["type"] == "text":
#                         full_response += block["text"] + "\n"
#
#                 result = send_message(system_prompt, history.get_turns(), [max_search_tool_tool])
#             else:
#                 if isinstance(result["content"], list):
#                     for block in result["content"]:
#                         if block["type"] == "text":
#                             full_response += block["text"] + "\n"
#                     history.add_turn_assistant(result["content"])
#                 else:
#                     full_response += result["content"]
#                     history.add_turn_assistant(result["content"])
#                 break
#
#         logger.info("Response successfully processed.")
#         return jsonify({"content": full_response.strip(), "session_id": session_id})
#
#     except requests.RequestException as e:
#         logger.error(f"Request to Anthropic API failed: {str(e)}", exc_info=True)
#         try:
#             # Try to parse the error message as JSON in case it's our custom message
#             error_content = json.loads(str(e))
#             if "content" in error_content:
#                 return jsonify(error_content), 429
#         except json.JSONDecodeError:
#             pass
#         # Fall back to generic error handling
#         return jsonify({"error": str(e)}), 500


# TODO: Flask chat endpoint export preserved for reference
# chat_endpoint = chat


# TODO: Functions preserved for reference - functionality moved to Django ViewSet
# def mock_post(url, headers, json_data):
#     try:
#         # Only check for __500__ test string - don't change message handling
#         has_500_test = "__500__" in str(json_data)
#         if has_500_test:
#             if not hasattr(mock_post, "has_returned_500"):
#                 mock_post.has_returned_500 = True
#                 mock_response = requests.Response()
#                 mock_response.status_code = 500
#                 mock_response._content = json.dumps(
#                     {
#                         "content": [
#                             {
#                                 "type": "text",
#                                 "text": "🫣 Uh-oh. I wasn't able to connect to the Anthropic API (my brain!) Please try sending your message again in about 1 minute?",
#                             }
#                         ],
#                         "isError": True,
#                     }
#                 ).encode("utf-8")
#                 return mock_response
#             else:
#                 delattr(mock_post, "has_returned_500")
#     except Exception as e:
#         logger.error(f"Error in mock_post: {str(e)}", exc_info=True)
#
#     # For all requests (including after first 500), use the real API
#     return requests.post(url, headers=headers, json=json_data)


# TODO: Flask main block preserved for reference
# if __name__ == "__main__":
#     try:
#         print("Starting Max's chat server on port 3000... 🦔")  # noqa: T201
#         app.run(port=3000, debug=True)
#     except KeyboardInterrupt:
#         print("\nShutting down Max's chat server... 👋")  # noqa: T201
#         sys.exit(0)
#     except Exception as e:
#         print(f"\n\n🔴 Oops! Something went wrong: {str(e)}\n")  # noqa: T201
#         sys.exit(1)
