from __future__ import annotations

import os

import pytest

from posthog.temporal.ingestion_acceptance_test.config import DEFAULT_LANE, configured_lanes, load_config

FLAT_ENV = {
    "INGESTION_ACCEPTANCE_TEST_API_HOST": "https://flat.example.com",
    "INGESTION_ACCEPTANCE_TEST_PROJECT_API_KEY": "phc_flat",
    "INGESTION_ACCEPTANCE_TEST_TEAM_ID": "111",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Strip ambient INGESTION_ACCEPTANCE_TEST_* vars so each test is hermetic."""
    for key in list(os.environ):
        if key.startswith("INGESTION_ACCEPTANCE_TEST_"):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


class TestLoadConfig:
    def test_flat_config_when_no_lane(self, clean_env: pytest.MonkeyPatch) -> None:
        for key, value in FLAT_ENV.items():
            clean_env.setenv(key, value)

        config = load_config()

        assert config.api_host == "https://flat.example.com"
        assert config.project_api_key == "phc_flat"
        assert config.team_id == 111
        assert config.lane == DEFAULT_LANE  # flat runs report as the "main" lane

    def test_lane_config_reads_per_lane_env(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_TURBO_API_HOST", "https://turbo.example.com/")
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_TURBO_PROJECT_API_KEY", "phc_turbo")
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_TURBO_TEAM_ID", "222")

        config = load_config("turbo")

        assert config.lane == "turbo"
        assert config.api_host == "https://turbo.example.com"  # trailing slash stripped
        assert config.project_api_key == "phc_turbo"
        assert config.team_id == 222

    def test_lane_name_normalized_to_env_segment(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_FAST_LANE_API_HOST", "https://fast.example.com")
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_FAST_LANE_PROJECT_API_KEY", "phc_fast")
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_FAST_LANE_TEAM_ID", "333")

        config = load_config("fast-lane")

        assert config.lane == "fast-lane"
        assert config.team_id == 333

    def test_missing_lane_env_raises_descriptive_error(self, clean_env: pytest.MonkeyPatch) -> None:
        with pytest.raises(ValueError, match="Lane 'turbo' is misconfigured"):
            load_config("turbo")

    def test_shared_settings_come_from_flat_env_for_lane(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_MAIN_API_HOST", "https://main.example.com")
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_MAIN_PROJECT_API_KEY", "phc_main")
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANE_MAIN_TEAM_ID", "444")
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_POLL_INTERVAL_SECONDS", "2.5")

        config = load_config("main")

        assert config.poll_interval_seconds == 2.5


class TestConfiguredLanes:
    def test_empty_when_unset(self, clean_env: pytest.MonkeyPatch) -> None:
        assert configured_lanes() == []

    def test_parses_comma_separated(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANES", "main,turbo")
        assert configured_lanes() == ["main", "turbo"]

    def test_strips_whitespace_and_blanks(self, clean_env: pytest.MonkeyPatch) -> None:
        clean_env.setenv("INGESTION_ACCEPTANCE_TEST_LANES", " main , , turbo ,")
        assert configured_lanes() == ["main", "turbo"]
