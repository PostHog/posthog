import os
import requests
from abc import ABC, abstractmethod
from typing import Optional

import dagster
from django.conf import settings
from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud
from posthog.models.web_preaggregated.team_selection import (
    DEFAULT_TOP_TEAMS_BY_PAGEVIEWS_LIMIT,
    get_top_teams_by_median_pageviews_sql,
)


class TeamSelectionStrategy(ABC):
    """Abstract base class for team selection strategies."""

    @abstractmethod
    def get_teams(self, context: dagster.OpExecutionContext) -> set[int]:
        """Get teams using this strategy."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get the strategy name."""
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

    def get_name(self) -> str:
        return "feature_enrollment"

    def _get_expected_host(self) -> Optional[str]:
        """Get the expected host for the current deployment region."""
        if not is_cloud():
            return None  # Don't filter by host for self-hosted instances

        if settings.SITE_URL == "https://us.posthog.com":
            return "us.posthog.com"
        elif settings.SITE_URL == "https://eu.posthog.com":
            return "eu.posthog.com"
        else:
            # Default to app.posthog.com for other cloud deployments
            return "app.posthog.com"

    def get_teams(self, context: dagster.OpExecutionContext) -> set[int]:
        flag_key = os.getenv("WEB_ANALYTICS_FEATURE_FLAG_KEY", "web-analytics-api")

        # Configuration for PostHog internal API - make parameters configurable
        api_host = os.getenv("POSTHOG_INTERNAL_API_HOST", "https://internal-t.posthog.com")
        api_token = os.getenv("POSTHOG_INTERNAL_API_TOKEN")
        team_id = int(os.getenv("POSTHOG_INTERNAL_TEAM_ID", "2"))  # PostHog's internal team ID

        # Get expected host for filtering
        expected_host = self._get_expected_host()

        if not api_token:
            context.log.warning("POSTHOG_INTERNAL_API_TOKEN not configured, falling back to local query")
            return self._get_teams_from_local_db(context, flag_key)

        try:
            # Build HogQL query with optional host filtering
            base_query = f"""
                SELECT DISTINCT
                    extract(properties.$current_url, '/project/([0-9]+)/') as project_id,
                    properties.$host
                FROM events
                WHERE event = '$feature_enrollment_update'
                AND timestamp >= '2025-07-01'
                AND properties.$feature_flag = '{flag_key}'
            """

            # Add host filtering if we have an expected host
            if expected_host:
                base_query += f" AND properties.$host = '{expected_host}'"
                context.log.info(f"Filtering enrollment data for host: {expected_host}")
            else:
                context.log.info("No host filtering applied (self-hosted instance)")

            base_query += " LIMIT 1000"

            query_payload = {
                "query": {
                    "kind": "HogQLQuery",
                    "query": base_query,
                }
            }

            headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
            url = f"{api_host}/api/environments/{team_id}/query/"

            context.log.info(f"Querying PostHog internal API for feature enrollment data (team_id: {team_id})")
            response = requests.post(url, json=query_payload, headers=headers, timeout=30)

            if response.status_code != 200:
                context.log.warning(
                    f"Failed to query PostHog internal API: {response.status_code} - {response.text[:200]}"
                )
                return self._get_teams_from_local_db(context, flag_key)

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

            host_info = f" on host '{expected_host}'" if expected_host else ""
            context.log.info(
                f"Found {len(team_ids)} teams with users enrolled in '{flag_key}'{host_info} via internal API"
            )
            return team_ids

        except requests.RequestException as e:
            context.log.warning(f"Error querying PostHog internal API: {e}")
            return self._get_teams_from_local_db(context, flag_key)
        except Exception as e:
            context.log.warning(f"Unexpected error in feature enrollment strategy: {e}")
            return self._get_teams_from_local_db(context, flag_key)

    def _get_teams_from_local_db(self, context: dagster.OpExecutionContext, flag_key: str) -> set[int]:
        """Fallback to local database query if API is not available."""
        try:
            from posthog.models.person.person import Person

            # Query PostgreSQL for teams with enrolled users
            enrollment_key = f"$feature_enrollment/{flag_key}"
            team_ids = (
                Person.objects.filter(**{f"properties__{enrollment_key}": True})
                .values_list("team_id", flat=True)
                .distinct()
            )

            team_ids_set = set(team_ids)
            context.log.info(f"Found {len(team_ids_set)} teams with users enrolled in '{flag_key}' from local DB")
            return team_ids_set

        except Exception as e:
            context.log.warning(f"Failed to get teams from local DB: {e}")
            return set()


class StrategyRegistry:
    def __init__(self):
        self._strategies: dict[str, TeamSelectionStrategy] = {}
        self._register_default_strategies()

    def _register_default_strategies(self):
        for strategy in [
            EnvironmentVariableStrategy(),
            HighPageviewsStrategy(),
            FeatureEnrollmentStrategy(),
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
