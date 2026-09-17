import time
import logging
from typing import Literal, Optional, TypedDict

from django.core.cache import caches


class RateLimitValues(TypedDict):
    max: float
    refill_rate: float


RateLimitType = Literal["requests", "input_tokens", "output_tokens"]


class ConversationHistory:
    # Rate limit configurations
    RATE_LIMITS: dict[RateLimitType, RateLimitValues] = {
        "requests": {"max": 4000.0, "refill_rate": 4000.0 / 60},  # 4000 per minute
        "input_tokens": {"max": 400000.0, "refill_rate": 400000.0 / 60},  # 400k per minute
        "output_tokens": {"max": 80000.0, "refill_rate": 80000.0 / 60},  # 80k per minute
    }
    MAX_BACKOFF = 40  # Maximum backoff in seconds

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

    @classmethod
    def get_from_cache(cls, session_id: str):
        """Get conversation history from cache"""
        cache = caches["default"]
        key = f"support_max_conversation_{session_id}"
        history = cache.get(key)
        if history is None:
            history = cls()
        return history

    def save_to_cache(self, session_id: str, timeout: int = 3600):  # 1 hour default
        """Save conversation history to cache"""
        cache = caches["default"]
        key = f"support_max_conversation_{session_id}"
        cache.set(key, self, timeout=timeout)

    @classmethod
    def _get_bucket_key(cls, limit_type: RateLimitType) -> str:
        """Get Redis key for a specific rate limit bucket"""
        return f"support_max_rate_limit_bucket_{limit_type}"

    @classmethod
    def _get_last_update_key(cls, limit_type: RateLimitType) -> str:
        """Get Redis key for tracking last bucket update time"""
        return f"support_max_rate_limit_last_update_{limit_type}"

    @classmethod
    def check_rate_limits(cls) -> tuple[bool, Optional[int], Optional[RateLimitType]]:
        """
        Check all rate limits using token bucket algorithm
        Returns (is_limited, retry_after, limit_type)
        """
        cache = caches["default"]
        now = time.time()

        for limit_type in cls.RATE_LIMITS:
            bucket_key = cls._get_bucket_key(limit_type)
            last_update_key = cls._get_last_update_key(limit_type)

            # Get current token count and last update time
            tokens = cache.get(bucket_key)
            last_update = cache.get(last_update_key)

            if tokens is None:
                # Initialize bucket if not exists
                tokens = cls.RATE_LIMITS[limit_type]["max"]
                last_update = now
                cache.set(bucket_key, tokens)
                cache.set(last_update_key, last_update)
            elif last_update is not None:
                # Calculate token replenishment
                time_passed = now - last_update
                new_tokens = time_passed * cls.RATE_LIMITS[limit_type]["refill_rate"]
                tokens = min(tokens + new_tokens, cls.RATE_LIMITS[limit_type]["max"])
                cache.set(bucket_key, tokens)
                cache.set(last_update_key, now)

            # Check if we have enough tokens
            if tokens < 1:
                # Calculate retry after based on refill rate
                retry_after = min(int((1 - tokens) / cls.RATE_LIMITS[limit_type]["refill_rate"]), cls.MAX_BACKOFF)
                return True, retry_after, limit_type

        return False, None, None

    @classmethod
    def consume_tokens(cls, limit_type: RateLimitType, amount: int = 1) -> bool:
        """
        Consume tokens from a specific bucket
        Returns True if tokens were consumed, False if not enough tokens
        """
        cache = caches["default"]
        bucket_key = cls._get_bucket_key(limit_type)
        last_update_key = cls._get_last_update_key(limit_type)

        # Get current token count
        tokens = cache.get(bucket_key)
        if tokens is None or tokens < amount:
            return False

        # Consume tokens
        cache.set(bucket_key, tokens - amount)
        cache.set(last_update_key, time.time())
        return True

    @classmethod
    def update_rate_limits(cls, headers: dict) -> None:
        """Update rate limit buckets based on API response headers"""
        cache = caches["default"]

        # Map header prefixes to limit types
        header_mapping: dict[str, RateLimitType] = {
            "anthropic-ratelimit-requests": "requests",
            "anthropic-ratelimit-input-tokens": "input_tokens",
            "anthropic-ratelimit-output-tokens": "output_tokens",
        }

        for header_prefix, limit_type in header_mapping.items():
            remaining = headers.get(f"{header_prefix}-remaining")
            if remaining is not None:
                try:
                    remaining = int(remaining)
                    bucket_key = cls._get_bucket_key(limit_type)
                    cache.set(bucket_key, remaining)
                    cache.set(cls._get_last_update_key(limit_type), time.time())
                except (ValueError, TypeError):
                    continue


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
