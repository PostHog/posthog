from typing import Optional

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, snapshot_clickhouse_queries

from posthog.schema import (
    DateRange,
    Filters,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionAttributionExplorerQuery,
    SessionAttributionGroupBy,
    SessionPropertyFilter,
    SessionTableVersion,
)

from posthog.hogql.constants import LimitContext

from posthog.hogql_queries.web_analytics.session_attribution_explorer_query_runner import (
    SessionAttributionExplorerQueryRunner,
)
from posthog.models.utils import uuid7


@snapshot_clickhouse_queries
class TestSessionAttributionQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_session(
        self, url=None, source=None, medium=None, campaign=None, gclid=None, gad_source=None, referring_domain="$direct"
    ):
        session_id = str(uuid7())
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=session_id,
            properties={
                "$session_id": session_id,
                "$current_url": url,
                "utm_source": source,
                "utm_medium": medium,
                "utm_campaign": campaign,
                "gclid": gclid,
                "gad_source": gad_source,
                "$referring_domain": referring_domain,
            },
        )

    def _create_data(self):
        # use powers of 2 for the number of sessions, so that all orderings are unambiguous (to ensure the test is deterministic)
        for _ in range(4):
            self._create_session(
                url="http://example.com/1a",
                source="source1",
                medium="medium1",
                campaign="campaign1a",
                referring_domain="referring_domain1a",
                gclid="gclid1a",
                gad_source="gad_source1a",
            )
        for _ in range(2):
            self._create_session(
                url="http://example.com/1b",
                source="source1",
                medium="medium1",
                campaign="campaign1b",
                referring_domain="referring_domain1b",
                gclid="gclid1b",
                gad_source="gad_source1b",
            )
        for _ in range(1):
            self._create_session(
                url="http://example.com/2",
                source="source2",
                medium="medium2",
                campaign="campaign2",
                referring_domain="referring_domain2",
            )

    def _run_session_attribution_query(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        group_by: Optional[list[SessionAttributionGroupBy]] = None,
        limit_context: Optional[LimitContext] = None,
        properties: Optional[list[SessionPropertyFilter]] = None,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        query = SessionAttributionExplorerQuery(
            filters=Filters(dateRange=DateRange(date_from=date_from, date_to=date_to), properties=properties or []),
            groupBy=group_by or [],
            modifiers=modifiers,
        )
        runner = SessionAttributionExplorerQueryRunner(team=self.team, query=query, limit_context=limit_context)
        return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_session_attribution_query().results
        assert results == [(0, [], [], [], [], [], [], [])]

    def test_group_by_nothing(self):
        self._create_data()

        results = self._run_session_attribution_query().results

        assert results == [
            (
                7,
                ["Paid Unknown", "Referral"],
                ["referring_domain1a", "referring_domain1b", "referring_domain2"],
                ["source1", "source2"],
                ["medium1", "medium2"],
                ["campaign1a", "campaign1b", "campaign2"],
                ["gclid,gad_source"],
                ["http://example.com/1a", "http://example.com/1b", "http://example.com/2"],
            )
        ]

    def test_group_by_initial_url(self):
        self._create_data()

        results = self._run_session_attribution_query(
            group_by=[SessionAttributionGroupBy.INITIAL_URL],
        ).results

        assert results == [
            (
                4,
                ["Paid Unknown"],
                ["referring_domain1a"],
                ["source1"],
                ["medium1"],
                ["campaign1a"],
                ["gclid,gad_source"],
                "http://example.com/1a",
            ),
            (
                2,
                ["Paid Unknown"],
                ["referring_domain1b"],
                ["source1"],
                ["medium1"],
                ["campaign1b"],
                ["gclid,gad_source"],
                "http://example.com/1b",
            ),
            (
                1,
                ["Referral"],
                ["referring_domain2"],
                ["source2"],
                ["medium2"],
                ["campaign2"],
                [],
                "http://example.com/2",
            ),
        ]

    def test_group_channel_medium_source(self):
        self._create_data()

        results = self._run_session_attribution_query(
            group_by=[
                SessionAttributionGroupBy.CHANNEL_TYPE,
                SessionAttributionGroupBy.MEDIUM,
                SessionAttributionGroupBy.SOURCE,
            ],
        ).results

        assert results == [
            (
                6,
                "Paid Unknown",
                ["referring_domain1a", "referring_domain1b"],
                "source1",
                "medium1",
                ["campaign1a", "campaign1b"],
                ["gclid,gad_source"],
                ["http://example.com/1a", "http://example.com/1b"],
            ),
            (1, "Referral", ["referring_domain2"], "source2", "medium2", ["campaign2"], [], ["http://example.com/2"]),
        ]

    def test_filters(self):
        self._create_data()

        results = self._run_session_attribution_query(
            group_by=[
                SessionAttributionGroupBy.CHANNEL_TYPE,
                SessionAttributionGroupBy.MEDIUM,
                SessionAttributionGroupBy.SOURCE,
            ],
            properties=[
                SessionPropertyFilter(key="$entry_utm_source", value="source1", operator=PropertyOperator.EXACT)
            ],
        ).results

        assert results == [
            (
                6,
                "Paid Unknown",
                ["referring_domain1a", "referring_domain1b"],
                "source1",
                "medium1",
                ["campaign1a", "campaign1b"],
                ["gclid,gad_source"],
                ["http://example.com/1a", "http://example.com/1b"],
            ),
        ]
