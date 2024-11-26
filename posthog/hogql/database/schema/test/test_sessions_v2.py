import uuid
from time import time_ns

import pytest
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.database.schema.sessions_v2 import (
    get_lazy_session_table_properties_v2,
    get_lazy_session_table_values_v2,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.models.property_definition import PropertyType
from posthog.models.utils import uuid7
from posthog.schema import HogQLQueryModifiers, SessionTableVersion, BounceRatePageViewMode, FilterLogicalOperator
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestSessionsV2(ClickhouseTestMixin, APIBaseTest):
    def __execute(self, query, bounce_rate_mode=BounceRatePageViewMode.COUNT_PAGEVIEWS):
        modifiers = HogQLQueryModifiers(
            sessionTableVersion=SessionTableVersion.V2, bounceRatePageViewMode=bounce_rate_mode
        )
        return execute_hogql_query(
            query=query,
            team=self.team,
            modifiers=modifiers,
        )

    def test_select_star_from_raw_sessions(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select * from raw_sessions",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )

    def test_select_star_from_sessions(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select * from sessions where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )

    @pytest.mark.skip(reason="doesn't work, didn't in V1 either so not a regression but should still be fixed")
    def test_select_event_sessions_star(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$current_url": "https://example.com", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select session.* from events where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        self.assertEqual(
            len(response.results or []),
            1,
        )

    def test_select_session_replay_session_duration(self):
        session_id = str(uuid7())

        response = self.__execute(
            parse_select(
                "select raw_session_replay_events.session.duration from raw_session_replay_events",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        self.assertEqual(
            len(response.results or []),
            0,  # just making sure the query runs
        )

    def test_channel_type(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"gad_source": "1", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select $channel_type from sessions where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        result = (response.results or [])[0]
        self.assertEqual(
            result[0],
            "Paid Search",
        )

    def test_event_dot_session_dot_channel_type(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"gad_source": "1", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select events.session.$channel_type from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        result = (response.results or [])[0]
        self.assertEqual(
            result[0],
            "Paid Search",
        )

    def test_events_session_dot_channel_type(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"gad_source": "1", "$session_id": session_id},
        )

        response = self.__execute(
            parse_select(
                "select session.$channel_type from events where $session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        result = (response.results or [])[0]
        self.assertEqual(
            result[0],
            "Paid Search",
        )

    def test_persons_and_sessions_on_events(self):
        p1 = _create_person(distinct_ids=["d1"], team=self.team)
        p2 = _create_person(distinct_ids=["d2"], team=self.team)

        s1 = str(uuid7())
        s2 = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1, "utm_source": "source1"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={"$session_id": s2, "utm_source": "source2"},
        )

        response = self.__execute(
            parse_select(
                "select events.person_id, session.$entry_utm_source from events where $session_id = {session_id} or $session_id = {session_id2} order by 2 asc",
                placeholders={"session_id": ast.Constant(value=s1), "session_id2": ast.Constant(value=s2)},
            ),
        )

        [row1, row2] = response.results or []
        self.assertEqual(row1, (p1.uuid, "source1"))
        self.assertEqual(row2, (p2.uuid, "source2"))

    def test_empty_counts(self):
        s1 = str(uuid7("2024-07-17"))
        d1 = "d1"
        _create_event(
            event="other_event",
            team=self.team,
            distinct_id=d1,
            properties={"$session_id": s1},
            timestamp="2024-07-17",
        )

        response = self.__execute(
            parse_select(
                "select uniqMerge(pageview_uniq), uniqMerge(autocapture_uniq), uniqMerge(screen_uniq) from raw_sessions",
            ),
        )
        self.assertEqual(response.results or [], [(0, 0, 0)])

        response = self.__execute(
            parse_select(
                "select $pageview_count, $autocapture_count, $screen_count from sessions where id = {session_id}",
                placeholders={"session_id": ast.Constant(value=s1)},
            ),
        )
        self.assertEqual(response.results or [], [(0, 0, 0)])

    def test_counts(self):
        s1 = str(uuid7())
        d1 = "d1"
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=d1,
            properties={"$session_id": s1},
            timestamp="2023-12-02",
        )
        for _ in range(2):
            _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id=d1,
                properties={"$session_id": s1},
                timestamp="2023-12-02",
            )
        for _ in range(3):
            _create_event(
                event="$screen",
                team=self.team,
                distinct_id=d1,
                properties={"$session_id": s1},
                timestamp="2023-12-02",
            )
        response = self.__execute(
            parse_select(
                "select $pageview_count, $autocapture_count, $screen_count from sessions where id = {session_id}",
                placeholders={"session_id": ast.Constant(value=s1)},
            ),
        )
        self.assertEqual(response.results or [], [(1, 2, 3)])

    def test_idempotent_event_counts(self):
        s1 = str(uuid7())
        d1 = "d1"
        pageview_uuid = str(uuid.uuid4())
        autocapture_uuid = str(uuid.uuid4())
        screen_uuid = str(uuid.uuid4())

        # simulate inserting the same event multiple times
        for _ in range(5):
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id=d1,
                properties={"$session_id": s1},
                timestamp="2023-12-02",
                event_uuid=pageview_uuid,
            )
            _create_event(
                event="$autocapture",
                team=self.team,
                distinct_id=d1,
                properties={"$session_id": s1},
                timestamp="2023-12-02",
                event_uuid=autocapture_uuid,
            )
            _create_event(
                event="$screen",
                team=self.team,
                distinct_id=d1,
                properties={"$session_id": s1},
                timestamp="2023-12-02",
                event_uuid=screen_uuid,
            )

        response = self.__execute(
            parse_select(
                "select $pageview_count, $autocapture_count, $screen_count from sessions where id = {session_id}",
                placeholders={"session_id": ast.Constant(value=s1)},
            ),
        )
        self.assertEqual(response.results or [], [(1, 1, 1)])

    def test_page_screen_autocapture_count_up_to(self):
        time = time_ns() // (10**6)

        # two pageviews
        s1 = str(uuid7(time))
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s1},
            timestamp="2023-12-02",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s1},
            timestamp="2023-12-03",
        )
        # one pageview and one autocapture
        s2 = str(uuid7(time + 2))
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s2},
            timestamp="2023-12-02",
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s2},
            timestamp="2023-12-03",
        )
        # one pageview
        s3 = str(uuid7(time + 3))
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s3},
            timestamp="2023-12-02",
        )
        # three pageviews (should still count as 2)
        s4 = str(uuid7(time + 4))
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s4},
            timestamp="2023-12-02",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s4},
            timestamp="2023-12-02",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s4},
            timestamp="2023-12-02",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s4},
            timestamp="2023-12-02",
        )
        # one screen
        s5 = str(uuid7(time + 5))
        _create_event(
            event="$screen",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s5},
            timestamp="2023-12-02",
        )

        results = (
            self.__execute(
                parse_select(
                    "select $page_screen_autocapture_count_up_to from sessions ORDER BY session_id",
                    placeholders={"session_id": ast.Constant(value=s1)},
                ),
            ).results
            or []
        )
        assert results == [(2,), (2,), (1,), (2,), (1,)]

    @parameterized.expand(
        [[BounceRatePageViewMode.UNIQ_PAGE_SCREEN_AUTOCAPTURES], [BounceRatePageViewMode.COUNT_PAGEVIEWS]]
    )
    def test_bounce_rate(self, bounce_rate_mode):
        time = time_ns() // (10**6)
        # ensure the sessions ids are sortable by giving them different time components
        s1a = str(uuid7(time))
        s1b = str(uuid7(time + 1))
        s2 = str(uuid7(time + 2))
        s3 = str(uuid7(time + 3))
        s4 = str(uuid7(time + 4))
        s5 = str(uuid7(time + 5))

        # person with 2 different sessions
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1a, "$current_url": "https://example.com/1"},
            timestamp="2023-12-02",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1a, "$current_url": "https://example.com/2"},
            timestamp="2023-12-03",
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1b, "$current_url": "https://example.com/3"},
            timestamp="2023-12-12",
        )
        # session with 1 pageview
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d2",
            properties={"$session_id": s2, "$current_url": "https://example.com/4"},
            timestamp="2023-12-11",
        )
        # session with 1 pageview and 1 autocapture
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d3",
            properties={"$session_id": s3, "$current_url": "https://example.com/5"},
            timestamp="2023-12-11",
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="d3",
            properties={"$session_id": s3, "$current_url": "https://example.com/5"},
            timestamp="2023-12-11",
        )
        # short session with a pageleave
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d4",
            properties={"$session_id": s4, "$current_url": "https://example.com/6"},
            timestamp="2023-12-11T12:00:00",
        )
        _create_event(
            event="$pageleave",
            team=self.team,
            distinct_id="d4",
            properties={"$session_id": s4, "$current_url": "https://example.com/6"},
            timestamp="2023-12-11T12:00:01",
        )
        # long session with a pageleave
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d5",
            properties={"$session_id": s5, "$current_url": "https://example.com/7"},
            timestamp="2023-12-11T12:00:00",
        )
        _create_event(
            event="$pageleave",
            team=self.team,
            distinct_id="d5",
            properties={"$session_id": s5, "$current_url": "https://example.com/7"},
            timestamp="2023-12-11T12:00:11",
        )
        response = self.__execute(
            parse_select(
                "select $is_bounce, session_id from sessions ORDER BY session_id",
            ),
            bounce_rate_mode=bounce_rate_mode,
        )
        assert (response.results or []) == [
            (0, s1a),
            (1, s1b),
            (1, s2),
            (0, s3),
            (1, s4),
            (0, s5),
        ]

    def test_last_external_click_url(self):
        s1 = str(uuid7())

        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1, "$external_click_url": "https://example.com/1"},
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="d1",
            properties={"$session_id": s1, "$external_click_url": "https://example.com/2"},
        )

        response = self.__execute(
            parse_select(
                "select $last_external_click_url from sessions where session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=s1)},
            ),
        )

        [row1] = response.results or []
        self.assertEqual(row1, ("https://example.com/2",))

    def test_lcp(self):
        s1 = str(uuid7("2024-10-01"))
        s2 = str(uuid7("2024-10-02"))
        s3 = str(uuid7("2024-10-03"))
        s4 = str(uuid7("2024-10-04"))

        # should be null if there's no $web_vitals_LCP_value
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s1,
            properties={"$session_id": s1, "$pathname": "/1"},
        )
        # should be able to read the property off the regular "$web_vitals" event
        _create_event(
            event="$web_vitals",
            team=self.team,
            distinct_id=s2,
            properties={"$session_id": s2, "$web_vitals_LCP_value": "2.0"},
        )
        # should be able to read the property off any event
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=s3,
            properties={"$session_id": s3, "$web_vitals_LCP_value": "3.0"},
        )
        # should take the first value if there's multiple
        _create_event(
            event="$web_vitals",
            team=self.team,
            distinct_id=s4,
            properties={"$session_id": s4, "$web_vitals_LCP_value": "4.1"},
        )
        _create_event(
            event="$web_vitals",
            team=self.team,
            distinct_id=s4,
            properties={"$session_id": s4, "$web_vitals_LCP_value": "4.2"},
        )
        response = self.__execute(
            parse_select("select $vitals_lcp from sessions order by session_id"),
        )

        rows = response.results or []
        assert rows == [(None,), (2.0,), (3.0,), (4.1,)]

    def test_can_use_v1_and_v2_fields(self):
        session_id = str(uuid7())

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="d1",
            properties={
                "$current_url": "https://example.com/pathname",
                "$pathname": "/pathname",
                "$session_id": session_id,
            },
        )

        response = self.__execute(
            parse_select(
                """
                select
                    $session_duration,
                    duration,
                    $end_current_url,
                    $exit_current_url,
                    $end_pathname,
                    $exit_pathname
                from sessions
                where session_id = {session_id}
                """,
                placeholders={"session_id": ast.Constant(value=session_id)},
            ),
        )

        assert response.results == [
            (0, 0, "https://example.com/pathname", "https://example.com/pathname", "/pathname", "/pathname")
        ]


class TestGetLazySessionProperties(ClickhouseTestMixin, APIBaseTest):
    def test_all(self):
        results = get_lazy_session_table_properties_v2(None)
        self.assertEqual(
            {r["id"] for r in results},
            {
                "$autocapture_count",
                "$channel_type",
                "$end_current_url",
                "$end_pathname",
                "$end_timestamp",
                "$entry_current_url",
                "$entry_gad_source",
                "$entry_gclid",
                "$entry_pathname",
                "$entry_referring_domain",
                "$entry_utm_campaign",
                "$entry_utm_content",
                "$entry_utm_medium",
                "$entry_utm_source",
                "$entry_utm_term",
                "$is_bounce",
                "$last_external_click_url",
                "$pageview_count",
                "$screen_count",
                "$session_duration",
                "$start_timestamp",
                "$vitals_lcp",
            },
        )
        self.assertEqual(
            results[0],
            {
                "id": "$start_timestamp",
                "is_numerical": False,
                "is_seen_on_filtered_events": None,
                "name": "$start_timestamp",
                "property_type": PropertyType.Datetime,
                "tags": [],
            },
        )

    def test_source(self):
        results = get_lazy_session_table_properties_v2("source")
        self.assertEqual(
            results,
            [
                {
                    "id": "$entry_utm_source",
                    "is_numerical": False,
                    "is_seen_on_filtered_events": None,
                    "name": "$entry_utm_source",
                    "property_type": PropertyType.String,
                    "tags": [],
                },
                {
                    "id": "$entry_gad_source",
                    "is_numerical": False,
                    "is_seen_on_filtered_events": None,
                    "name": "$entry_gad_source",
                    "property_type": PropertyType.String,
                    "tags": [],
                },
            ],
        )

    def test_entry_utm(self):
        results = get_lazy_session_table_properties_v2("entry utm")
        self.assertEqual(
            [result["name"] for result in results],
            ["$entry_utm_source", "$entry_utm_campaign", "$entry_utm_medium", "$entry_utm_term", "$entry_utm_content"],
        )

    def test_can_get_values_for_all(self):
        results = get_lazy_session_table_properties_v2(None)
        for prop in results:
            get_lazy_session_table_values_v2(key=prop["id"], team=self.team, search_term=None)

    def test_custom_channel_types(self):
        self.team.modifiers = {
            "customChannelTypeRules": [
                {"items": [], "combiner": FilterLogicalOperator.AND_, "channel_type": "Test Channel Type", "id": "1"},
                {"items": [], "combiner": FilterLogicalOperator.AND_, "channel_type": "Paid Social", "id": "2"},
                {"items": [], "combiner": FilterLogicalOperator.AND_, "channel_type": "Test Channel Type", "id": "3"},
            ]
        }
        self.team.save()
        results = get_lazy_session_table_values_v2(key="$channel_type", team=self.team, search_term=None)
        # the custom channel types should be first, there's should be no duplicates, and any custom rules for existing
        # channel types should be bumped to the top
        assert results == [
            ["Test Channel Type"],
            ["Paid Social"],
            ["Cross Network"],
            ["Paid Search"],
            ["Paid Video"],
            ["Paid Shopping"],
            ["Paid Unknown"],
            ["Direct"],
            ["Organic Search"],
            ["Organic Social"],
            ["Organic Video"],
            ["Organic Shopping"],
            ["Push"],
            ["SMS"],
            ["Audio"],
            ["Email"],
            ["Referral"],
            ["Affiliate"],
            ["Unknown"],
        ]
