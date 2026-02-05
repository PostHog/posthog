"""Configuration loading from environment variables using pydantic-settings."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuration for acceptance tests.

    All values are loaded from environment variables with the INGESTION_ACCEPTANCE_TEST_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix="INGESTION_ACCEPTANCE_TEST_",
        frozen=True,
    )

    api_host: str
    project_api_key: str
    project_id: str
    personal_api_key: str
    event_timeout_seconds: int = Field(default=300)
    poll_interval_seconds: float = Field(default=30.0)
    slack_webhook_url: str | None = Field(default=None)

    @field_validator("api_host")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def to_safe_dict(self) -> dict[str, str]:
        """Return configuration as a dictionary with sensitive values redacted."""
        return {
            "api_host": self.api_host,
            "project_id": self.project_id,
            "event_timeout_seconds": str(self.event_timeout_seconds),
            "poll_interval_seconds": str(self.poll_interval_seconds),
        }
