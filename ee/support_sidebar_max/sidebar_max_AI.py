import time
import logging


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
            # Simple text responses
            self.turns.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                        }
                    ],
                }
            )

    def get_turns(self):
        self.touch()  # Update timestamp on activity
        return self.turns


# Active logging configuration used by ViewSet
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

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
