from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from parameterized import parameterized

from products.product_analytics.backend.models.insight import Insight


def _trends_query(
    interval: str | None = "day",
    math: str = "total",
    trends_filter: dict | None = None,
    date_range: dict | None = None,
    wrapped: bool = True,
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "kind": "TrendsQuery",
        "series": [{"kind": "EventsNode", "event": "$pageview", "math": math}],
        "trendsFilter": {"hideWeekends": True, **(trends_filter or {})},
    }
    if interval is not None:
        source["interval"] = interval
    if date_range is not None:
        source["dateRange"] = date_range
    if not wrapped:
        return source
    return {"kind": "InsightVizNode", "source": source}


class TestMigrateHideWeekends(BaseTest):
    def _run(self, query: dict[str, Any], **command_kwargs: Any) -> dict[str, Any]:
        insight = Insight.objects.create(team=self.team, saved=True, query=query)
        call_command("migrate_hide_weekends", **command_kwargs)
        insight.refresh_from_db()
        query = insight.query
        return query["source"] if query.get("kind") == "InsightVizNode" else query

    @parameterized.expand([("wrapped", True), ("bare", False)])
    def test_day_interval_simple_math_migrates_to_weekday_days_of_week(self, _name: str, wrapped: bool) -> None:
        source = self._run(_trends_query(wrapped=wrapped))
        assert source["dateRange"]["daysOfWeek"] == [1, 2, 3, 4, 5]
        assert "hideWeekends" not in source["trendsFilter"]

    def test_no_op_interval_strips_flag_without_adding_days_of_week(self) -> None:
        source = self._run(_trends_query(interval="week"))
        assert "hideWeekends" not in source["trendsFilter"]
        assert "daysOfWeek" not in (source.get("dateRange") or {})

    def test_unset_interval_defaults_to_day_and_migrates(self) -> None:
        source = self._run(_trends_query(interval=None))
        assert source["dateRange"]["daysOfWeek"] == [1, 2, 3, 4, 5]

    def test_existing_days_of_week_intersects_with_weekdays(self) -> None:
        source = self._run(_trends_query(date_range={"date_from": "-30d", "daysOfWeek": [1, 2, 3, 6]}))
        assert source["dateRange"]["daysOfWeek"] == [1, 2, 3]
        assert source["dateRange"]["date_from"] == "-30d"
        assert "hideWeekends" not in source["trendsFilter"]

    @parameterized.expand(
        [
            ("weekly_active_math", _trends_query(math="weekly_active")),
            ("cumulative_display", _trends_query(trends_filter={"display": "ActionsLineGraphCumulative"})),
            ("smoothing", _trends_query(trends_filter={"smoothingIntervals": 7})),
            ("weekend_only_days_of_week", _trends_query(date_range={"daysOfWeek": [6, 7]})),
        ]
    )
    def test_result_changing_cohorts_are_left_untouched(self, _name: str, query: dict[str, Any]) -> None:
        source = self._run(query)
        assert source["trendsFilter"]["hideWeekends"] is True
        assert (source.get("dateRange") or {}).get("daysOfWeek") != [1, 2, 3, 4, 5]

    def test_dry_run_writes_nothing(self) -> None:
        source = self._run(_trends_query(), dry_run=True)
        assert source["trendsFilter"]["hideWeekends"] is True
        assert "dateRange" not in source
