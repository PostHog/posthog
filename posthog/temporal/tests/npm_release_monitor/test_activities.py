from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.npm_release_monitor.activities import (
    CorrelateReleasesInput,
    FetchGitHubWorkflowRunsInput,
    FetchNpmVersionsInput,
    correlate_releases,
    fetch_github_workflow_runs,
    fetch_npm_versions,
)


class TestFetchNpmVersions:
    @pytest.mark.asyncio
    async def test_fetches_versions_from_npm_registry(self):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "time": {
                    "created": "2020-01-01T00:00:00.000Z",
                    "modified": "2024-01-15T12:00:00.000Z",
                    "1.0.0": "2024-01-10T10:00:00.000Z",
                    "1.0.1": "2024-01-15T12:00:00.000Z",
                }
            }
        )

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await fetch_npm_versions(
                FetchNpmVersionsInput(
                    packages=["posthog-js"],
                    since_timestamp="2024-01-01T00:00:00+00:00",
                )
            )

        assert len(result.versions) == 2
        assert result.versions[0]["package"] == "posthog-js"
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_handles_404_gracefully(self):
        mock_response = AsyncMock()
        mock_response.status = 404

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await fetch_npm_versions(
                FetchNpmVersionsInput(packages=["nonexistent-package"], since_timestamp=None)
            )

        assert len(result.versions) == 0
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_filters_versions_by_since_timestamp(self):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "time": {
                    "1.0.0": "2024-01-01T10:00:00.000Z",
                    "1.0.1": "2024-01-15T12:00:00.000Z",
                }
            }
        )

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await fetch_npm_versions(
                FetchNpmVersionsInput(
                    packages=["posthog-js"],
                    since_timestamp="2024-01-10T00:00:00+00:00",
                )
            )

        assert len(result.versions) == 1
        assert result.versions[0]["version"] == "1.0.1"


class TestFetchGitHubWorkflowRuns:
    @pytest.mark.asyncio
    async def test_fetches_workflow_runs(self):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "workflow_runs": [
                    {
                        "name": "Release",
                        "conclusion": "success",
                        "created_at": "2024-01-15T11:55:00Z",
                        "html_url": "https://github.com/PostHog/posthog-js/actions/runs/123",
                    }
                ]
            }
        )

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_response)))

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await fetch_github_workflow_runs(
                FetchGitHubWorkflowRunsInput(
                    repos=["PostHog/posthog-js"],
                    since_timestamp="2024-01-01T00:00:00+00:00",
                    github_token="test-token",
                )
            )

        assert len(result.runs) == 1
        assert result.runs[0]["workflow_name"] == "Release"
        assert result.runs[0]["conclusion"] == "success"


class TestCorrelateReleases:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "time_diff_minutes,expected_correlated",
        [
            (5, True),
            (9, True),
            (11, False),
            (60, False),
        ],
    )
    async def test_correlation_time_window(self, time_diff_minutes, expected_correlated):
        publish_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        workflow_time = publish_time - timedelta(minutes=time_diff_minutes)

        npm_versions = [
            {
                "package": "posthog-js",
                "version": "1.0.1",
                "published_at": publish_time.isoformat(),
            }
        ]
        github_runs = [
            {
                "repo": "PostHog/posthog-js",
                "workflow_name": "Release",
                "conclusion": "success",
                "created_at": workflow_time.isoformat(),
                "html_url": "https://github.com/PostHog/posthog-js/actions/runs/123",
            }
        ]
        packages_config = [
            {
                "npm_package": "posthog-js",
                "github_repo": "PostHog/posthog-js",
                "workflow_names": ["Release"],
                "time_window_minutes": 10,
            }
        ]

        result = await correlate_releases(
            CorrelateReleasesInput(
                npm_versions=npm_versions,
                github_runs=github_runs,
                packages_config=packages_config,
            )
        )

        if expected_correlated:
            assert len(result.correlated_releases) == 1
            assert len(result.unauthorized_releases) == 0
        else:
            assert len(result.correlated_releases) == 0
            assert len(result.unauthorized_releases) == 1

    @pytest.mark.asyncio
    async def test_detects_unauthorized_release_no_matching_workflow(self):
        npm_versions = [
            {
                "package": "posthog-js",
                "version": "1.0.1",
                "published_at": "2024-01-15T12:00:00+00:00",
            }
        ]
        packages_config = [
            {
                "npm_package": "posthog-js",
                "github_repo": "PostHog/posthog-js",
                "workflow_names": ["Release"],
                "time_window_minutes": 10,
            }
        ]

        result = await correlate_releases(
            CorrelateReleasesInput(
                npm_versions=npm_versions,
                github_runs=[],
                packages_config=packages_config,
            )
        )

        assert len(result.unauthorized_releases) == 1
        assert result.unauthorized_releases[0]["package"] == "posthog-js"
        assert "No matching CI/CD workflow run found" in result.unauthorized_releases[0]["reason"]

    @pytest.mark.asyncio
    async def test_ignores_failed_workflow_runs(self):
        publish_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        workflow_time = publish_time - timedelta(minutes=5)

        npm_versions = [
            {
                "package": "posthog-js",
                "version": "1.0.1",
                "published_at": publish_time.isoformat(),
            }
        ]
        github_runs = [
            {
                "repo": "PostHog/posthog-js",
                "workflow_name": "Release",
                "conclusion": "failure",
                "created_at": workflow_time.isoformat(),
                "html_url": "https://github.com/PostHog/posthog-js/actions/runs/123",
            }
        ]
        packages_config = [
            {
                "npm_package": "posthog-js",
                "github_repo": "PostHog/posthog-js",
                "workflow_names": ["Release"],
                "time_window_minutes": 10,
            }
        ]

        result = await correlate_releases(
            CorrelateReleasesInput(
                npm_versions=npm_versions,
                github_runs=github_runs,
                packages_config=packages_config,
            )
        )

        assert len(result.unauthorized_releases) == 1
        assert len(result.correlated_releases) == 0

    @pytest.mark.asyncio
    async def test_matches_partial_workflow_name(self):
        publish_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        workflow_time = publish_time - timedelta(minutes=5)

        npm_versions = [
            {
                "package": "posthog-js",
                "version": "1.0.1",
                "published_at": publish_time.isoformat(),
            }
        ]
        github_runs = [
            {
                "repo": "PostHog/posthog-js",
                "workflow_name": "Release to npm",
                "conclusion": "success",
                "created_at": workflow_time.isoformat(),
                "html_url": "https://github.com/PostHog/posthog-js/actions/runs/123",
            }
        ]
        packages_config = [
            {
                "npm_package": "posthog-js",
                "github_repo": "PostHog/posthog-js",
                "workflow_names": ["Release"],
                "time_window_minutes": 10,
            }
        ]

        result = await correlate_releases(
            CorrelateReleasesInput(
                npm_versions=npm_versions,
                github_runs=github_runs,
                packages_config=packages_config,
            )
        )

        assert len(result.correlated_releases) == 1
        assert len(result.unauthorized_releases) == 0
