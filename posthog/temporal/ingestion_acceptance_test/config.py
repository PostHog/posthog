"""Configuration loading from environment variables using pydantic-settings."""

import os

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "INGESTION_ACCEPTANCE_TEST_"
DEFAULT_LANE = "main"


class Config(BaseSettings):
    """Configuration for acceptance tests.

    All values are loaded from environment variables with the INGESTION_ACCEPTANCE_TEST_ prefix.
    """

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        frozen=True,
    )

    api_host: str
    project_api_key: str
    team_id: int
    lane: str = Field(default=DEFAULT_LANE)
    event_timeout_seconds: int = Field(default=3600)
    poll_interval_seconds: float = Field(default=10.0)
    activity_timeout_seconds: int = Field(default=3600)
    slack_webhook_url: str | None = Field(default=None)

    @field_validator("api_host")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    def to_safe_dict(self) -> dict[str, str]:
        """Return configuration as a dictionary with sensitive values redacted."""
        return {
            "api_host": self.api_host,
            "team_id": str(self.team_id),
            "lane": self.lane,
            "event_timeout_seconds": str(self.event_timeout_seconds),
            "poll_interval_seconds": str(self.poll_interval_seconds),
            "activity_timeout_seconds": str(self.activity_timeout_seconds),
        }


def _lane_env_segment(lane: str) -> str:
    """Normalize a lane name into its env var segment (e.g. "turbo" -> "TURBO")."""
    return lane.strip().upper().replace("-", "_")


def configured_lanes() -> list[str]:
    """Lane names to schedule, parsed from INGESTION_ACCEPTANCE_TEST_LANES.

    The value is a comma-separated list (e.g. "main,turbo") and is set per
    environment, so each region schedules only the lanes it declares. Returns an
    empty list when unset, in which case callers fall back to the single
    flat-config schedule (the pre-lane behavior).
    """
    raw = os.environ.get(f"{ENV_PREFIX}LANES", "")
    return [name.strip() for name in raw.split(",") if name.strip()]


def load_config(lane: str | None = None) -> Config:
    """Build a Config for the given lane.

    When lane is None, config is read from the flat INGESTION_ACCEPTANCE_TEST_*
    env vars (the pre-lane behavior).

    When a lane is given, api_host, team_id and project_api_key are read from the
    per-lane env vars INGESTION_ACCEPTANCE_TEST_LANE_<LANE>_{API_HOST,TEAM_ID,PROJECT_API_KEY}.
    Shared settings (timeouts, Slack webhook) still come from the flat env vars.

    Raises:
        ValueError: if the lane's required per-lane env vars are not set.
    """
    if lane is None:
        return Config()

    prefix = f"{ENV_PREFIX}LANE_{_lane_env_segment(lane)}_"
    try:
        api_host = os.environ[f"{prefix}API_HOST"]
        project_api_key = os.environ[f"{prefix}PROJECT_API_KEY"]
        team_id = int(os.environ[f"{prefix}TEAM_ID"])
    except KeyError as e:
        raise ValueError(f"Lane {lane!r} is misconfigured: missing env var {e.args[0]}") from e

    return Config(
        lane=lane,
        api_host=api_host,
        project_api_key=project_api_key,
        team_id=team_id,
    )
