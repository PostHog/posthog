from typing import Optional, Union

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    DateRange,
    HogQLQueryModifiers,
    SessionTableVersion,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebExternalClicksTableQuery,
)

from posthog.hogql_queries.web_analytics.external_clicks import WebExternalClicksTableQueryRunner
from posthog.models.utils import uuid7


@snapshot_clickhouse_queries
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
        order_by: Optional[list[Union[WebAnalyticsOrderByFields, WebAnalyticsOrderByDirection]]] = None,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        query = WebExternalClicksTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            limit=limit,
            filterTestAccounts=filter_test_accounts,
            stripQueryParams=strip_query_params,
            orderBy=order_by,
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
                ["https://www.example.com/", (2, 0), (2, 0)],
                ["https://www.example.com/login", (1, 0), (1, 0)],
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
                ["https://www.example.com/", (2, 0), (2, 0)],
                ["https://www.example.com/docs", (1, 0), (1, 0)],
                ["https://www.example.com/login", (1, 0), (1, 0)],
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
            [["https://www.example.com/", (1, 0), (1, 0)], ["https://www.example.com/login", (1, 0), (1, 0)]],
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
            [["https://www.example.com/login", (1, 0), (2, 0)]],
            results_strip,
        )

        results_no_strip = self._run_external_clicks_table_query(
            "2023-12-01", "2023-12-03", filter_test_accounts=False, strip_query_params=False
        ).results

        self.assertEqual(
            [
                ["https://www.example.com/login#bar", (1, 0), (1, 0)],
                ["https://www.example.com/login?test=1#foo", (1, 0), (1, 0)],
            ],
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
                ["https://other.com/", (1, 0), (1, 0)],
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
                ["https://other.com/", (1, 0), (1, 0)],
            ],
            results,
        )

    def test_custom_order_by(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2023-12-02"))
        s3 = str(uuid7("2023-12-02"))

        # Create events with different click counts and visitor counts:
        # - example.com: 4 clicks from 3 visitors
        # - beta.com: 5 clicks from 2 visitors
        # - alpha.com: 1 click from 1 visitor
        self._create_events(
            [
                (
                    "user1",
                    [
                        ("2023-12-02", s1, "https://example.com/"),
                        ("2023-12-02", s1, "https://example.com/"),
                        ("2023-12-02", s1, "https://beta.com/"),
                    ],
                ),
                (
                    "user2",
                    [
                        ("2023-12-02", s2, "https://example.com/"),
                        ("2023-12-02", s2, "https://beta.com/"),
                        ("2023-12-02", s2, "https://beta.com/"),
                        ("2023-12-02", s2, "https://beta.com/"),
                        ("2023-12-02", s2, "https://beta.com/"),
                    ],
                ),
                (
                    "user3",
                    [
                        ("2023-12-02", s3, "https://example.com/"),
                        ("2023-12-02", s3, "https://alpha.com/"),
                    ],
                ),
            ]
        )

        default_results = self._run_external_clicks_table_query(
            "2023-12-01",
            "2023-12-03",
            filter_test_accounts=False,
        ).results

        self.assertEqual(
            default_results,
            [
                ["https://beta.com/", (2, 0), (5, 0)],
                ["https://example.com/", (3, 0), (4, 0)],
                ["https://alpha.com/", (1, 0), (1, 0)],
            ],
            "Default sorting should be by clicks DESC, then URL ASC",
        )

        visitors_desc_results = self._run_external_clicks_table_query(
            "2023-12-01",
            "2023-12-03",
            filter_test_accounts=False,
            order_by=[WebAnalyticsOrderByFields.VISITORS, WebAnalyticsOrderByDirection.DESC],
        ).results

        self.assertEqual(
            visitors_desc_results,
            [
                ["https://example.com/", (3, 0), (4, 0)],
                ["https://beta.com/", (2, 0), (5, 0)],
                ["https://alpha.com/", (1, 0), (1, 0)],
            ],
            "Sorting by visitors DESC should show URLs with more visitors first, then alphabetically",
        )
