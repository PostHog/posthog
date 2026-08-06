from typing import Any, Optional

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from posthog.management.commands.migrate_hide_weekends import ISO_WEEKDAYS

from products.product_analytics.backend.models.insight import Insight


def trends_insight_query(
    interval: Optional[str] = None,
    display: Optional[str] = None,
    math: Optional[str] = None,
    smoothing_intervals: Optional[int] = None,
    days_of_week: Optional[list[int]] = None,
    hide_weekends: bool = True,
    wrapped: bool = True,
) -> dict:
    trends_filter: dict[str, Any] = {"hideWeekends": hide_weekends, "showLegend": True}
    if display:
        trends_filter["display"] = display
    if smoothing_intervals:
        trends_filter["smoothingIntervals"] = smoothing_intervals
    series: dict[str, Any] = {"kind": "EventsNode", "event": "$pageview"}
    if math:
        series["math"] = math
    date_range: dict[str, Any] = {"date_from": "-30d"}
    if days_of_week:
        date_range["daysOfWeek"] = days_of_week
    source = {
        "kind": "TrendsQuery",
        "series": [series],
        "trendsFilter": trends_filter,
        "dateRange": date_range,
    }
    if interval:
        source["interval"] = interval
    if not wrapped:
        return source
    return {"kind": "InsightVizNode", "source": source}


class TestMigrateHideWeekends(BaseTest):
    def _source(self, insight: Insight) -> dict:
        insight.refresh_from_db()
        query = insight.query
        return query["source"] if query.get("kind") == "InsightVizNode" else query

    @parameterized.expand(
        [
            ("day interval line graph", {}),
            ("explicit day interval", {"interval": "day"}),
            ("bare trends query without viz wrapper", {"wrapped": False}),
        ]
    )
    def test_switches_result_identical_insights_to_days_of_week(self, _name: str, kwargs: dict) -> None:
        insight = Insight.objects.create(team=self.team, query=trends_insight_query(**kwargs))

        call_command("migrate_hide_weekends")

        source = self._source(insight)
        assert "hideWeekends" not in source["trendsFilter"]
        assert source["dateRange"]["daysOfWeek"] == ISO_WEEKDAYS
        # the rewrite merges into the existing date range and keeps unrelated filter keys
        assert source["dateRange"]["date_from"] == "-30d"
        assert source["trendsFilter"]["showLegend"] is True

    @parameterized.expand(
        [
            ("week interval", {"interval": "week"}),
            ("hour interval", {"interval": "hour"}),
            ("bold number display", {"display": "BoldNumber"}),
            ("pie display", {"display": "ActionsPie"}),
            ("hourly weekly active users", {"interval": "hour", "math": "weekly_active"}),
        ]
    )
    def test_strips_flag_where_it_has_no_effect(self, _name: str, kwargs: dict) -> None:
        insight = Insight.objects.create(team=self.team, query=trends_insight_query(**kwargs))

        call_command("migrate_hide_weekends")

        source = self._source(insight)
        assert "hideWeekends" not in source["trendsFilter"]
        assert "daysOfWeek" not in source["dateRange"]

    @parameterized.expand(
        [
            ("weekly active users math", {"math": "weekly_active"}),
            ("monthly active users math", {"math": "monthly_active"}),
            ("cumulative display", {"display": "ActionsLineGraphCumulative"}),
            ("smoothing", {"smoothing_intervals": 7}),
            ("days of week already set", {"days_of_week": [1, 2, 3]}),
            ("second interval", {"interval": "second"}),
        ]
    )
    def test_keeps_insights_whose_results_would_change(self, _name: str, kwargs: dict) -> None:
        query = trends_insight_query(**kwargs)
        insight = Insight.objects.create(team=self.team, query=query)

        call_command("migrate_hide_weekends")

        insight.refresh_from_db()
        assert insight.query == query

    def test_does_not_touch_unrelated_or_deleted_insights(self) -> None:
        off = Insight.objects.create(team=self.team, query=trends_insight_query(hide_weekends=False))
        funnel = Insight.objects.create(
            team=self.team,
            query={"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery", "series": []}},
        )
        deleted = Insight.objects.create(team=self.team, query=trends_insight_query(), deleted=True)

        call_command("migrate_hide_weekends")

        for insight, before in [(off, off.query), (funnel, funnel.query), (deleted, deleted.query)]:
            insight.refresh_from_db()
            assert insight.query == before

    def test_migration_does_not_bump_last_modified_at(self) -> None:
        insight = Insight.objects.create(team=self.team, query=trends_insight_query())
        before = insight.last_modified_at

        call_command("migrate_hide_weekends")

        insight.refresh_from_db()
        assert "hideWeekends" not in self._source(insight)["trendsFilter"]
        assert insight.last_modified_at == before

    def test_dry_run_changes_nothing(self) -> None:
        insight = Insight.objects.create(team=self.team, query=trends_insight_query())

        call_command("migrate_hide_weekends", "--dry-run")

        source = self._source(insight)
        assert source["trendsFilter"]["hideWeekends"] is True
        assert "daysOfWeek" not in source["dateRange"]

    def test_team_id_scopes_the_run(self) -> None:
        insight = Insight.objects.create(team=self.team, query=trends_insight_query())

        call_command("migrate_hide_weekends", "--team-id", str(self.team.pk + 1))

        source = self._source(insight)
        assert source["trendsFilter"]["hideWeekends"] is True
