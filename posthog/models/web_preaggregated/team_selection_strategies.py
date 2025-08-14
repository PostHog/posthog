import os
import requests
from abc import ABC, abstractmethod

import dagster
from django.conf import settings
from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.models.web_preaggregated.team_selection import (
    DEFAULT_TOP_TEAMS_BY_PAGEVIEWS_LIMIT,
    get_top_teams_by_median_pageviews_sql,
)
from posthog.tasks.early_access_feature import POSTHOG_TEAM_ID


class TeamSelectionStrategy(ABC):
    @abstractmethod
    def get_teams(self, context: dagster.OpExecutionContext) -> set[int]:
        pass

    @abstractmethod
    def get_name(self) -> str:
        pass


class EnvironmentVariableStrategy(TeamSelectionStrategy):
    """Select teams from environment variable configuration."""

    def get_name(self) -> str:
        return "environment_variable"

    def get_teams(self, context: dagster.OpExecutionContext) -> set[int]:
        env_teams = os.getenv("WEB_ANALYTICS_ENABLED_TEAM_IDS")
        if not env_teams:
            context.log.info("No teams found in WEB_ANALYTICS_ENABLED_TEAM_IDS environment variable")
            return set()

        team_ids = set()
        invalid_ids = []

        for tid in env_teams.split(","):
            tid = tid.strip()
            if tid:
                try:
                    team_ids.add(int(tid))
                except ValueError:
                    invalid_ids.append(tid)

        if invalid_ids:
            context.log.warning(f"Invalid team IDs in environment variable: {invalid_ids}")

        context.log.info(f"Found {len(team_ids)} valid teams from environment variable")
        return team_ids


class HighPageviewsStrategy(TeamSelectionStrategy):
    """Select teams with the highest pageview counts (default: 30)."""

    def get_name(self) -> str:
        return "high_pageviews"

    def get_teams(self, context: dagster.OpExecutionContext) -> set[int]:
        try:
            limit = int(os.getenv("WEB_ANALYTICS_TOP_TEAMS_LIMIT", str(DEFAULT_TOP_TEAMS_BY_PAGEVIEWS_LIMIT)))
            sql = get_top_teams_by_median_pageviews_sql(limit)
            result = sync_execute(sql)
            team_ids = {row[0] for row in result}
            context.log.info(f"Found {len(team_ids)} teams with high pageviews")
            return team_ids
        except ValueError as e:
            context.log.warning(f"Invalid configuration for pageviews query: {e}")
            return set()
        except Exception as e:
            context.log.warning(f"Failed to fetch top teams by pageviews: {e}")
            return set()


class FeatureEnrollmentStrategy(TeamSelectionStrategy):
    """Select teams where users have enrolled in a specific feature preview (default: web-analytics-api)."""

    def __init__(
        self,
        api_host: str = "https://internal-t.posthog.com",
        api_token: str | None = None,
        flag_key: str = "web-analytics-api",
        since_date: str = "2025-07-01",
        team_id: int | None = None,
    ):
        self.api_host = api_host
        self.api_token = api_token
        self.flag_key = flag_key
        self.since_date = since_date
        self.team_id = team_id or POSTHOG_TEAM_ID

    def get_name(self) -> str:
        return "feature_enrollment"

    def _get_region_host(self) -> str:
        return settings.SITE_URL.removeprefix("https://")

    def get_teams(self, context: dagster.OpExecutionContext) -> set[int]:
        if not self.api_token:
            context.log.error(
                "WEB_ANALYTICS_FEATURE_ENROLLMENT_API_TOKEN not configured, cannot fetch feature enrollment data"
            )  # noqa: TRY400
            return set()

        if not is_cloud():
            context.log.warning(
                "Skipping feature enrollment strategy for self-hosted instances. This strategy is only available on posthog cloud."
            )  # noqa: TRY400
            return set()

        # Get host so we only add the teams from the appropriate region to the CH dictionary
        environment_host = self._get_region_host()

        try:
            # Build HogQL query with parameterized values for security
            base_query = """
                SELECT DISTINCT
                    extract(properties.$current_url, '/project/([0-9]+)/') as project_id,
                    properties.$host
                FROM events
                WHERE event = '$feature_enrollment_update'
                    AND properties.$host = {environment_host}
                    AND timestamp >= {since_date}
                    AND properties.$feature_flag = {flag_key}
            """

            query_payload = {
                "query": {
                    "kind": "HogQLQuery",
                    "query": base_query,
                    "values": {
                        "environment_host": environment_host,
                        "since_date": self.since_date,
                        "flag_key": self.flag_key,
                    },
                    "limit": MAX_SELECT_RETURNED_ROWS,
                }
            }

            headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}
            url = f"{self.api_host}/api/environments/{self.team_id}/query/"

            context.log.info(f"Querying PostHog internal API for feature enrollment data (team_id: {self.team_id})")
            response = requests.post(url, json=query_payload, headers=headers, timeout=30)

            if response.status_code != 200:
                context.log.error(
                    f"Failed to query PostHog internal API: {response.status_code} - {response.text[:200]}"
                )  # noqa: TRY400
                return set()

            data = response.json()
            results = data.get("results", [])

            # Extract team IDs from the response
            team_ids = set()
            for row in results:
                if row and row[0]:  # project_id is in the first column
                    try:
                        team_ids.add(int(row[0]))
                    except (ValueError, TypeError):
                        context.log.debug(f"Invalid project_id: {row[0]}")

            host_info = f" on host '{environment_host}'" if environment_host else ""
            context.log.info(
                f"Found {len(team_ids)} teams with users enrolled in '{self.flag_key}'{host_info} via internal API"
            )
            return team_ids

        except requests.RequestException as e:
            context.log.error(f"Error querying PostHog internal API: {e}")  # noqa: TRY400
            return set()
        except Exception as e:
            context.log.error(f"Unexpected error in feature enrollment strategy: {e}")  # noqa: TRY400
            return set()


class StrategyRegistry:
    """
    This class is the source for all available strategies we can use to enable the pre-aggregated tables for teams.

    The actual strategies to be used are configured in the environment variable WEB_ANALYTICS_TEAM_SELECTION_STRATEGIES because we may have different strategies for different environments.
    """

    def __init__(self):
        self._strategies: dict[str, TeamSelectionStrategy] = {}
        self._register_default_strategies()

    def _register_default_strategies(self):
        for strategy in [
            EnvironmentVariableStrategy(),
            HighPageviewsStrategy(),
            FeatureEnrollmentStrategy(
                api_host=os.getenv("WEB_ANALYTICS_FEATURE_ENROLLMENT_API_HOST", "https://internal-t.posthog.com"),
                api_token=os.getenv("WEB_ANALYTICS_FEATURE_ENROLLMENT_API_TOKEN"),
                flag_key=os.getenv("WEB_ANALYTICS_API_FEATURE_PREVIEW_FLAG_KEY", "web-analytics-api"),
            ),
        ]:
            self.register(strategy)

    def register(self, strategy: TeamSelectionStrategy):
        self._strategies[strategy.get_name()] = strategy

    def get_strategy(self, name: str) -> TeamSelectionStrategy | None:
        return self._strategies.get(name.lower())

    def get_available_strategies(self) -> list[str]:
        return sorted(self._strategies.keys())


# Global registry instance
strategy_registry = StrategyRegistry()
