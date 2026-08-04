import copy
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.product_analytics.backend.models.insight import Insight


class TestMigrateHideWeekends(BaseTest):
    def _run_wrapped(self, source: dict[str, Any], **command_kwargs: Any) -> dict[str, Any]:
        insight = Insight.objects.create(team=self.team, saved=True, query={"kind": "InsightVizNode", "source": source})
        call_command("migrate_hide_weekends", **command_kwargs)
        insight.refresh_from_db()
        query = insight.query or {}
        return query["source"]

    @parameterized.expand(
        [
            (
                "wrapped",
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "interval": "day",
                        "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                        "trendsFilter": {"hideWeekends": True},
                    },
                },
            ),
            (
                "bare",
                {
                    "kind": "TrendsQuery",
                    "interval": "day",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                    "trendsFilter": {"hideWeekends": True},
                },
            ),
        ]
    )
    def test_day_interval_simple_math_migrates_to_weekday_days_of_week(self, _name: str, query: dict[str, Any]) -> None:
        insight = Insight.objects.create(team=self.team, saved=True, query=query)
        call_command("migrate_hide_weekends")
        insight.refresh_from_db()
        saved_query = insight.query or {}
        source = saved_query["source"] if saved_query.get("kind") == "InsightVizNode" else saved_query
        assert source["dateRange"]["daysOfWeek"] == [1, 2, 3, 4, 5]
        assert "hideWeekends" not in source["trendsFilter"]

    def test_no_op_interval_strips_flag_without_adding_days_of_week(self) -> None:
        source = self._run_wrapped(
            {
                "kind": "TrendsQuery",
                "interval": "week",
                "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                "trendsFilter": {"hideWeekends": True},
            }
        )
        assert "hideWeekends" not in source["trendsFilter"]
        assert "dateRange" not in source

    def test_unset_interval_defaults_to_day_and_migrates(self) -> None:
        source = self._run_wrapped(
            {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                "trendsFilter": {"hideWeekends": True},
            }
        )
        assert source["dateRange"]["daysOfWeek"] == [1, 2, 3, 4, 5]

    def test_existing_days_of_week_intersects_with_weekdays(self) -> None:
        source = self._run_wrapped(
            {
                "kind": "TrendsQuery",
                "interval": "day",
                "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                "trendsFilter": {"hideWeekends": True},
                "dateRange": {"date_from": "-30d", "daysOfWeek": [1, 2, 3, 6]},
            }
        )
        assert source["dateRange"]["daysOfWeek"] == [1, 2, 3]
        assert source["dateRange"]["date_from"] == "-30d"
        assert "hideWeekends" not in source["trendsFilter"]

    @parameterized.expand(
        [
            (
                "weekly_active_math",
                {
                    "kind": "TrendsQuery",
                    "interval": "day",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "weekly_active"}],
                    "trendsFilter": {"hideWeekends": True},
                },
            ),
            (
                "cumulative_display",
                {
                    "kind": "TrendsQuery",
                    "interval": "day",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                    "trendsFilter": {"hideWeekends": True, "display": "ActionsLineGraphCumulative"},
                },
            ),
            (
                "smoothing",
                {
                    "kind": "TrendsQuery",
                    "interval": "day",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                    "trendsFilter": {"hideWeekends": True, "smoothingIntervals": 7},
                },
            ),
            (
                "weekend_only_days_of_week",
                {
                    "kind": "TrendsQuery",
                    "interval": "day",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
                    "trendsFilter": {"hideWeekends": True},
                    "dateRange": {"daysOfWeek": [6, 7]},
                },
            ),
        ]
    )
    def test_result_changing_cohorts_are_left_untouched(self, _name: str, query: dict[str, Any]) -> None:
        expected = copy.deepcopy(query)
        source = self._run_wrapped(query)
        assert source == expected

    def test_dry_run_writes_nothing(self) -> None:
        query = {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
            "trendsFilter": {"hideWeekends": True},
        }
        expected = copy.deepcopy(query)
        source = self._run_wrapped(query, dry_run=True)
        assert source == expected

    def test_only_migrates_hide_weekends_insights_for_the_selected_team(self) -> None:
        other_team = self.organization.teams.create()
        hide_weekends_query = {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
            "trendsFilter": {"hideWeekends": True},
        }
        plain_query = {
            "kind": "TrendsQuery",
            "interval": "day",
            "series": [{"kind": "EventsNode", "event": "$pageview", "math": "total"}],
            "trendsFilter": {},
        }
        target_insight = Insight.objects.create(
            team=self.team, saved=True, query={"kind": "InsightVizNode", "source": copy.deepcopy(hide_weekends_query)}
        )
        untouched_same_team_insight = Insight.objects.create(
            team=self.team, saved=True, query={"kind": "InsightVizNode", "source": copy.deepcopy(plain_query)}
        )
        untouched_other_team_insight = Insight.objects.create(
            team=other_team, saved=True, query={"kind": "InsightVizNode", "source": copy.deepcopy(hide_weekends_query)}
        )

        call_command("migrate_hide_weekends", team_id=self.team.pk)

        target_insight.refresh_from_db()
        untouched_same_team_insight.refresh_from_db()
        untouched_other_team_insight.refresh_from_db()

        target_query = target_insight.query or {}
        same_team_query = untouched_same_team_insight.query or {}
        other_team_query = untouched_other_team_insight.query or {}
        assert target_query["source"]["dateRange"]["daysOfWeek"] == [1, 2, 3, 4, 5]
        assert "hideWeekends" not in target_query["source"]["trendsFilter"]
        assert same_team_query["source"] == plain_query
        assert other_team_query["source"] == hide_weekends_query
