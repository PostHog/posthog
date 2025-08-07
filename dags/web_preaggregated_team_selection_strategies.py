import os
from abc import ABC, abstractmethod

import dagster
from posthog.clickhouse.client import sync_execute
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

    def get_teams(self, context: dagster.OpExecutionContext) -> set[int]:
        flag_key = os.getenv("WEB_ANALYTICS_FEATURE_FLAG_KEY", "web-analytics-api")

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
            context.log.info(f"Found {len(team_ids_set)} teams with users enrolled in '{flag_key}'")
            return team_ids_set

        except Exception as e:
            context.log.warning(f"Failed to get teams with feature enrollment for '{flag_key}': {e}")
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
