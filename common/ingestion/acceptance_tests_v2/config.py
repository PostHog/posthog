"""Configuration loading from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Configuration for acceptance tests.

    All values are loaded from environment variables.
    """

    api_host: str
    project_api_key: str
    project_id: str
    personal_api_key: str
    event_timeout_seconds: int = 30
    poll_interval_seconds: float = 2.0

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables.

        Required environment variables:
            POSTHOG_API_HOST: Base URL of PostHog API (e.g., https://app.posthog.com)
            POSTHOG_PROJECT_API_KEY: Project API key for event capture
            POSTHOG_PROJECT_ID: Project ID for querying events
            POSTHOG_PERSONAL_API_KEY: Personal API key for private API access

        Optional environment variables:
            POSTHOG_EVENT_TIMEOUT_SECONDS: Timeout for waiting for events (default: 30)
            POSTHOG_POLL_INTERVAL_SECONDS: Interval between polling attempts (default: 2.0)

        Raises:
            ValueError: If any required environment variable is missing.
        """
        required_vars = {
            "POSTHOG_API_HOST": "api_host",
            "POSTHOG_PROJECT_API_KEY": "project_api_key",
            "POSTHOG_PROJECT_ID": "project_id",
            "POSTHOG_PERSONAL_API_KEY": "personal_api_key",
        }

        missing = [var for var in required_vars if not os.environ.get(var)]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Please set these variables before running acceptance tests."
            )

        return cls(
            api_host=os.environ["POSTHOG_API_HOST"].rstrip("/"),
            project_api_key=os.environ["POSTHOG_PROJECT_API_KEY"],
            project_id=os.environ["POSTHOG_PROJECT_ID"],
            personal_api_key=os.environ["POSTHOG_PERSONAL_API_KEY"],
            event_timeout_seconds=int(os.environ.get("POSTHOG_EVENT_TIMEOUT_SECONDS", "30")),
            poll_interval_seconds=float(os.environ.get("POSTHOG_POLL_INTERVAL_SECONDS", "2.0")),
        )

    def to_safe_dict(self) -> dict[str, str]:
        """Return configuration as a dictionary with sensitive values redacted."""
        return {
            "api_host": self.api_host,
            "project_id": self.project_id,
            "project_api_key": f"{self.project_api_key[:8]}...{self.project_api_key[-4:]}"
            if len(self.project_api_key) > 12
            else "***",
            "personal_api_key": f"{self.personal_api_key[:8]}...{self.personal_api_key[-4:]}"
            if len(self.personal_api_key) > 12
            else "***",
            "event_timeout_seconds": str(self.event_timeout_seconds),
            "poll_interval_seconds": str(self.poll_interval_seconds),
        }
