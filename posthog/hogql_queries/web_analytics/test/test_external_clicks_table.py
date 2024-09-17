from typing import Optional

from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.external_clicks import WebExternalClicksTableQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import (
    DateRange,
    SessionTableVersion,
    HogQLQueryModifiers,
    WebExternalClicksTableQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestExternalClicksTableQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
                        "$external_click_url": click,
                        "$host": "www.host.com",
                        **properties,
                    },
                    elements_chain=f'a:href="{click}"',
                )
        return person_result

    def _run_external_clicks_table_query(
        self,
        date_from,
        date_to,
        limit=None,
        properties=None,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        filter_test_accounts: Optional[bool] = False,
        strip_query_params: Optional[bool] = False,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        query = WebExternalClicksTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            limit=limit,
            filterTestAccounts=filter_test_accounts,
            stripQueryParams=strip_query_params,
        )
        runner = WebExternalClicksTableQueryRunner(team=self.team, query=query, modifiers=modifiers)
        return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_external_clicks_table_query("2023-12-08", "2023-12-15").results
        self.assertEqual([], results)

    def test_increase_in_users(
        self,
    ):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1a, "https://www.example.com/"),
                        ("2023-12-03", s1a, "https://www.example.com/login"),
                        ("2023-12-13", s1b, "https://www.example.com/docs"),
                    ],
                ),
                ("p2", [("2023-12-10", s2, "https://www.example.com/")]),
            ]
        )

        results = self._run_external_clicks_table_query("2023-12-01", "2023-12-11").results

        self.assertEqual(
            [
                ["https://www.example.com/", 2, 2],
                ["https://www.example.com/login", 1, 1],
            ],
            results,
        )

    def test_all_time(self):
        s1a = str(uuid7("2023-12-02"))
        s1b = str(uuid7("2023-12-13"))
        s2 = str(uuid7("2023-12-10"))
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2023-12-02", s1a, "https://www.example.com/"),
                        ("2023-12-03", s1a, "https://www.example.com/login"),
                        ("2023-12-13", s1b, "https://www.example.com/docs"),
                    ],
                ),
                ("p2", [("2023-12-10", s2, "https://www.example.com/")]),
            ]
        )

        results = self._run_external_clicks_table_query("all", "2023-12-15").results

        self.assertEqual(
            [
                ["https://www.example.com/", 2, 2],
                ["https://www.example.com/docs", 1, 1],
                ["https://www.example.com/login", 1, 1],
            ],
            results,
        )

    def test_filter_test_accounts(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events(
            [
                (
                    "test",
                    [
                        ("2023-12-02", s1, "https://www.example.com/"),
                        ("2023-12-03", s1, "https://www.example.com/login"),
                    ],
                )
            ]
        )

        results = self._run_external_clicks_table_query("2023-12-01", "2023-12-03", filter_test_accounts=True).results

        self.assertEqual(
            [],
            results,
        )

    def test_dont_filter_test_accounts(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events(
            [
                (
                    "test",
                    [
                        ("2023-12-02", s1, "https://www.example.com/"),
                        ("2023-12-03", s1, "https://www.example.com/login"),
                    ],
                )
            ]
        )

        results = self._run_external_clicks_table_query("2023-12-01", "2023-12-03", filter_test_accounts=False).results

        self.assertEqual(
            [["https://www.example.com/", 1, 1], ["https://www.example.com/login", 1, 1]],
            results,
        )

    def test_strip_query_params(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events(
            [
                (
                    "test",
                    [
                        ("2023-12-02", s1, "https://www.example.com/login?test=1#foo"),
                        ("2023-12-03", s1, "https://www.example.com/login#bar"),
                    ],
                )
            ]
        )

        results_strip = self._run_external_clicks_table_query(
            "2023-12-01", "2023-12-03", filter_test_accounts=False, strip_query_params=True
        ).results

        self.assertEqual(
            [["https://www.example.com/login", 1, 2]],
            results_strip,
        )

        results_no_strip = self._run_external_clicks_table_query(
            "2023-12-01", "2023-12-03", filter_test_accounts=False, strip_query_params=False
        ).results

        self.assertEqual(
            [["https://www.example.com/login#bar", 1, 1], ["https://www.example.com/login?test=1#foo", 1, 1]],
            results_no_strip,
        )

    def test_should_exclude_subdomain_under_root(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events(
            [
                (
                    "test",
                    [
                        ("2023-12-02", s1, "https://subdomain.host.com/", {"$host": "host.com"}),
                        ("2023-12-03", s1, "https://host.com/", {"$host": "host.com"}),
                        ("2023-12-03", s1, "https://other.com/", {"$host": "host.com"}),
                    ],
                )
            ]
        )

        results = self._run_external_clicks_table_query("2023-12-01", "2023-12-03", filter_test_accounts=False).results

        self.assertEqual(
            [
                ["https://other.com/", 1, 1],
            ],
            results,
        )

    def test_should_exclude_subdomain_with_shared_root(self):
        s1 = str(uuid7("2023-12-02"))
        # Create 1 test account
        self._create_events(
            [
                (
                    "test",
                    [
                        ("2023-12-02", s1, "https://subdomain.host.com/", {"$host": "subdomain.host.com"}),
                        ("2023-12-02", s1, "https://other.host.com/", {"$host": "subdomain.host.com"}),
                        ("2023-12-03", s1, "https://host.com/", {"$host": "subdomain.host.com"}),
                        ("2023-12-03", s1, "https://other.com/", {"$host": "subdomain.host.com"}),
                    ],
                )
            ]
        )

        results = self._run_external_clicks_table_query("2023-12-01", "2023-12-03", filter_test_accounts=False).results

        self.assertEqual(
            [
                ["https://other.com/", 1, 1],
            ],
            results,
        )
