import json

from unittest.mock import MagicMock, patch

from parameterized import parameterized

import posthog.dags.common.health.jobs.growth.sdk_outdated as sdk_outdated_mod
from posthog.dags.common.health.jobs.growth.sdk_outdated import SDK_DOCS_URLS, detect_sdk_outdated
from posthog.models.health_issue import HealthIssue


def _make_team_cache(sdks: dict[str, str], timestamp: str = "2026-02-19T12:00:00") -> bytes:
    data = {}
    for lib, version in sdks.items():
        data[lib] = [{"lib_version": version, "max_timestamp": timestamp, "count": 1000}]
    return json.dumps(data).encode()


def _make_github_cache(sdk: str, version: str) -> bytes:
    return json.dumps({"latestVersion": version, "releaseDates": {}}).encode()


def _make_redis_side_effect(team_data: dict | None, github_data: dict[str, str] | None) -> callable:
    store: dict[str, bytes | None] = {}
    if team_data is not None:
        store["sdk_versions:team:1"] = _make_team_cache(team_data)
    if github_data is not None:
        for sdk, version in github_data.items():
            store[f"github:sdk_versions:{sdk}"] = _make_github_cache(sdk, version)
    return lambda key: store.get(key)


class TestDetectSdkOutdated:
    def setup_method(self):
        sdk_outdated_mod._github_cache = None

    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_no_team_cache_returns_none(self, mock_get_client):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = _make_redis_side_effect(
            team_data=None,
            github_data={"web": "1.142.0"},
        )

        result = detect_sdk_outdated(1, MagicMock())

        assert result is None

    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_no_github_cache_returns_none(self, mock_get_client):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = _make_redis_side_effect(
            team_data={"web": "1.120.0"},
            github_data=None,
        )

        result = detect_sdk_outdated(1, MagicMock())

        assert result is None

    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_empty_team_data_returns_healthy(self, mock_get_client):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = lambda key: {
            "sdk_versions:team:1": json.dumps({}).encode(),
            "github:sdk_versions:web": _make_github_cache("web", "1.142.0"),
        }.get(key)

        result = detect_sdk_outdated(1, MagicMock())

        assert result == []

    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_all_sdks_up_to_date_returns_healthy(self, mock_get_client):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = _make_redis_side_effect(
            team_data={"web": "1.142.0", "posthog-python": "3.8.0"},
            github_data={"web": "1.142.0", "posthog-python": "3.8.0"},
        )

        result = detect_sdk_outdated(1, MagicMock())

        assert result == []

    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_one_sdk_outdated(self, mock_get_client):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = _make_redis_side_effect(
            team_data={"web": "1.120.0"},
            github_data={"web": "1.142.0"},
        )

        result = detect_sdk_outdated(1, MagicMock())

        assert result is not None
        assert len(result) == 1
        assert result[0].severity == HealthIssue.Severity.WARNING
        assert result[0].payload == {
            "sdk_name": "web",
            "current_version": "1.120.0",
            "latest_version": "1.142.0",
            "last_seen_at": "2026-02-19T12:00:00",
            "docs_url": "https://posthog.com/docs/libraries/js",
        }
        assert result[0].hash_keys == ["sdk_name"]

    @parameterized.expand(
        [
            (
                "mixed_one_outdated",
                {"web": "1.120.0", "posthog-python": "3.8.0"},
                {"web": "1.142.0", "posthog-python": "3.8.0"},
                1,
                ["web"],
            ),
            (
                "both_outdated",
                {"web": "1.120.0", "posthog-node": "4.0.0"},
                {"web": "1.142.0", "posthog-node": "4.3.1"},
                2,
                ["web", "posthog-node"],
            ),
        ]
    )
    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_multiple_sdks(self, _name, team_sdks, github_sdks, expected_count, expected_sdk_names, mock_get_client):
        sdk_outdated_mod._github_cache = None
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = _make_redis_side_effect(
            team_data=team_sdks,
            github_data=github_sdks,
        )

        result = detect_sdk_outdated(1, MagicMock())

        assert result is not None
        assert len(result) == expected_count
        actual_names = sorted(r.payload["sdk_name"] for r in result)
        assert actual_names == sorted(expected_sdk_names)

    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_unknown_sdk_in_team_data_is_ignored(self, mock_get_client):
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = lambda key: {
            "sdk_versions:team:1": json.dumps(
                {"unknown-sdk": [{"lib_version": "1.0.0", "max_timestamp": "2026-02-19T12:00:00", "count": 100}]}
            ).encode(),
            "github:sdk_versions:web": _make_github_cache("web", "1.142.0"),
        }.get(key)

        result = detect_sdk_outdated(1, MagicMock())

        assert result == []

    @parameterized.expand(
        [
            ("web", "https://posthog.com/docs/libraries/js"),
            ("posthog-python", "https://posthog.com/docs/libraries/python"),
            ("posthog-node", "https://posthog.com/docs/libraries/node"),
        ]
    )
    @patch("posthog.dags.common.health.jobs.growth.sdk_outdated.get_client")
    def test_docs_url_per_sdk(self, sdk_name, expected_url, mock_get_client):
        sdk_outdated_mod._github_cache = None
        mock_redis = MagicMock()
        mock_get_client.return_value = mock_redis
        mock_redis.get.side_effect = _make_redis_side_effect(
            team_data={sdk_name: "0.0.1"},
            github_data={sdk_name: "99.0.0"},
        )

        result = detect_sdk_outdated(1, MagicMock())

        assert result is not None
        assert len(result) == 1
        assert result[0].payload["docs_url"] == expected_url

    def test_all_sdk_types_have_docs_urls(self):
        from products.growth.dags.github_sdk_versions import SDK_TYPES

        for sdk_type in SDK_TYPES:
            assert sdk_type in SDK_DOCS_URLS, f"Missing docs URL for {sdk_type}"
