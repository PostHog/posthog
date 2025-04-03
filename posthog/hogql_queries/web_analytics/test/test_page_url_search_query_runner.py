from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.page_url_search_query_runner import PageUrlSearchQueryRunner
from posthog.models.utils import uuid7
from posthog.schema import (
    DateRange,
    WebAnalyticsPageURLSearchQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from posthog.clickhouse.client import sync_execute


class TestPageUrlSearchQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def _create_events(self, data, event="$pageview"):
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
            for timestamp, session_id, *extra in timestamps:
                url = None
                elements = None
                screen_name = None
                current_url = None

                if event == "$pageview":
                    url = extra[0] if extra else None
                    if len(extra) > 1 and isinstance(extra[1], dict) and "$current_url" in extra[1]:
                        current_url = extra[1]["$current_url"]
                        del extra[1]["$current_url"]
                    else:
                        current_url = "http://www.example.com" + url if url else None
                elif event == "$screen":
                    screen_name = extra[0] if extra else None
                elif event == "$autocapture":
                    elements = extra[0] if extra else None

                properties = extra[1] if extra and len(extra) > 1 else {}

                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={
                        "$session_id": session_id,
                        "$pathname": url,
                        "$current_url": current_url,
                        "$screen_name": screen_name,
                        **properties,
                    },
                    elements=elements,
                )
        return person_result

    def _run_page_url_search_query(
        self,
        date_from,
        date_to,
        search_term=None,
        limit=None,
        strip_query_params=False,
        properties=None,
        sampling_factor=None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = WebAnalyticsPageURLSearchQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=properties or [],
                search_term=search_term,
                limit=limit,
                strip_query_params=strip_query_params,
                # Use 1.0 as default for testing to ensure all events are included in the sample
                # The default in production is 0.1 (10%), but that would be unreliable for tests with few events
                sampling_factor=sampling_factor or 1.0,
            )
            runner = PageUrlSearchQueryRunner(team=self.team, query=query)
            return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_page_url_search_query(
            "2025-01-22",
            "2025-01-29",
        ).results
        assert [] == results

    def test_search_by_term(self):
        s1 = str(uuid7("2025-01-22"))
        s2 = str(uuid7("2025-01-25"))
        s3 = str(uuid7("2025-01-26"))
        
        # Create test events with proper URLs
        self._create_events(
            [
                (
                    "p1", 
                    [
                        (
                            "2025-01-22", 
                            s1, 
                            "/products/123", 
                            {"$current_url": "http://www.example.com/products/123"}
                        )
                    ]
                ),
                (
                    "p2", 
                    [
                        (
                            "2025-01-25", 
                            s2, 
                            "/products/456", 
                            {"$current_url": "http://www.example.com/products/456"}
                        )
                    ]
                ),
                (
                    "p3", 
                    [
                        (
                            "2025-01-26", 
                            s3, 
                            "/about", 
                            {"$current_url": "http://www.example.com/about"}
                        )
                    ]
                ),
            ]
        )
        
        # Directly check if events were created correctly
        all_events = sync_execute(
            """
            SELECT 
                event,
                toString(replaceRegexpAll(
                    nullIf(nullIf(JSONExtractRaw(properties, '$current_url'), ''), 'null'), 
                    '^"|"$', ''
                )) AS current_url
            FROM events 
            WHERE team_id = %(team_id)s
            ORDER BY current_url
            """,
            {"team_id": self.team.pk}
        )
        
        # Verify we have 3 events with the correct URLs
        assert len(all_events) == 3, f"Expected 3 events, got {len(all_events)}"
        
        # Run the search query with "product" term
        search_results = self._run_page_url_search_query(
            "2025-01-22",
            "2025-01-29",
            search_term="product",
        )
        
        # Check if the search query generated appropriate results
        results = search_results.results
        
        # Should find only the product URLs
        assert len(results) == 2, f"Expected 2 results for 'product' search, got {len(results)}"
        urls = [result.url for result in results]
        assert all("product" in url for url in urls), f"URLs don't all contain 'product': {urls}"
        assert "http://www.example.com/products/123" in urls, "Missing expected URL"
        assert "http://www.example.com/products/456" in urls, "Missing expected URL"

    def test_strip_query_params(self):
        s1 = str(uuid7("2025-01-22"))

        # Create events with query parameters in URLs
        self._create_events(
            [
                (
                    "p1",
                    [
                        (
                            "2025-01-22",
                            s1,
                            "/products",
                            {"$current_url": "http://www.example.com/products?ref=homepage&utm_source=google"},
                        ),
                        (
                            "2025-01-22",
                            s1,
                            "/products",
                            {"$current_url": "http://www.example.com/products?ref=sidebar&utm_source=facebook"},
                        ),
                        (
                            "2025-01-22",
                            s1,
                            "/about",
                            {"$current_url": "http://www.example.com/about?utm_source=google"},
                        ),
                    ],
                ),
            ]
        )

        # First query without stripping query parameters - should see 3 different URLs
        results_with_params = self._run_page_url_search_query(
            "2025-01-22",
            "2025-01-29",
            strip_query_params=False,
        ).results

        assert len(results_with_params) == 3

        # Now query with stripping query parameters - should see 2 unique base URLs
        results_without_params = self._run_page_url_search_query(
            "2025-01-22",
            "2025-01-29",
            strip_query_params=True,
        ).results

        assert len(results_without_params) == 2
        urls = [result.url for result in results_without_params]
        assert "http://www.example.com/products" in urls
        assert "http://www.example.com/about" in urls

    def test_query_with_limit(self):
        s1 = str(uuid7("2025-01-22"))

        # Create multiple pageview events
        self._create_events(
            [
                (
                    "p1",
                    [
                        ("2025-01-22", s1, "/page1"),
                        ("2025-01-22", s1, "/page2"),
                        ("2025-01-22", s1, "/page3"),
                        ("2025-01-22", s1, "/page4"),
                        ("2025-01-22", s1, "/page5"),
                    ],
                ),
            ]
        )

        # Query with limit=2, should return only 2 results
        response = self._run_page_url_search_query(
            "2025-01-22",
            "2025-01-29",
            limit=2,
        )

        assert len(response.results) == 2
        assert response.hasMore is True  # Should indicate more results are available

    def _count_events_in_clickhouse(self):
        result = sync_execute(
            """
            SELECT count(*) 
            FROM events 
            WHERE team_id = %(team_id)s
            """,
            {"team_id": self.team.pk}
        )
        return result[0][0]

    def _inspect_event_data(self):
        result = sync_execute(
            """
            SELECT event, 
                   distinct_id, 
                   toString(timestamp), 
                   toString(properties)
            FROM events 
            WHERE team_id = %(team_id)s
            LIMIT 10
            """,
            {"team_id": self.team.pk}
        )
        return result

    def _check_current_url_data(self):
        """Check if current_url properties are correctly stored and can be queried"""
        result = sync_execute(
            """
            SELECT 
                event,
                toString(replaceRegexpAll(
                    nullIf(nullIf(JSONExtractRaw(properties, '$current_url'), ''), 'null'), 
                    '^"|"$', ''
                )) AS current_url,
                toString(replaceRegexpAll(
                    nullIf(nullIf(JSONExtractRaw(properties, '$pathname'), ''), 'null'), 
                    '^"|"$', ''
                )) AS pathname
            FROM events 
            WHERE team_id = %(team_id)s
            LIMIT 10
            """,
            {"team_id": self.team.pk}
        )
        return result
