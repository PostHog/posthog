from typing import Optional, Union

from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.active_hours_heatmap_query_runner import ActiveHoursHeatMapQueryRunner
from posthog.schema import (
    DateRange,
    SessionTableVersion,
    HogQLQueryModifiers,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    ActiveHoursHeatMapQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

@snapshot_clickhouse_queries
class TestActiveHoursHeatMapQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$autocapture"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )
            for timestamp, session_id, click, *rest in timestamps:
                properties = rest[0] if rest else {}

                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$event_type": "click",
                        "$host": "www.host.com",
                        **properties,
                    },
                    elements_chain=f'a:href="{click}"',
                )
        return person_result

    def _run_active_hours_heatmap_query_runner(
        self,
        date_from,
        date_to,
        properties=None,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        filter_test_accounts: Optional[bool] = False,
        order_by: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        query = ActiveHoursHeatMapQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            filterTestAccounts=filter_test_accounts,
            orderBy=order_by,
        )
        runner = ActiveHoursHeatMapQueryRunner(team=self.team, query=query, modifiers=modifiers)
        return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_active_hours_heatmap_query_runner("2023-12-08", "2023-12-15").results
        self.assertEqual([], results)
