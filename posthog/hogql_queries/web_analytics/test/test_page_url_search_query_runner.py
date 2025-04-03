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


@snapshot_clickhouse_queries
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
                sampling_factor=sampling_factor,
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
        
        self._create_events(
            [
                ("p1", [("2025-01-22", s1, "/products/123")]),
                ("p2", [("2025-01-25", s2, "/products/456")]),
                ("p3", [("2025-01-26", s3, "/about")]),
            ]
        )

        results = self._run_page_url_search_query(
            "2025-01-22",
            "2025-01-29",
            search_term="product",
        ).results

        # Should find only the product URLs
        assert len(results) == 2
        urls = [result["url"] for result in results]
        assert all("product" in url for url in urls)
        
    def test_strip_query_params(self):
        s1 = str(uuid7("2025-01-22"))
        
        # Create events with query parameters in URLs
        self._create_events(
            [
                ("p1", [
                    ("2025-01-22", s1, "/products", {"$current_url": "http://www.example.com/products?ref=homepage&utm_source=google"}),
                    ("2025-01-22", s1, "/products", {"$current_url": "http://www.example.com/products?ref=sidebar&utm_source=facebook"}),
                    ("2025-01-22", s1, "/about", {"$current_url": "http://www.example.com/about?utm_source=google"}),
                ]),
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
        urls = [result["url"] for result in results_without_params]
        assert "http://www.example.com/products" in urls
        assert "http://www.example.com/about" in urls
        
    def test_query_with_limit(self):
        s1 = str(uuid7("2025-01-22"))
        
        # Create multiple pageview events
        self._create_events(
            [
                ("p1", [
                    ("2025-01-22", s1, "/page1"),
                    ("2025-01-22", s1, "/page2"),
                    ("2025-01-22", s1, "/page3"),
                    ("2025-01-22", s1, "/page4"),
                    ("2025-01-22", s1, "/page5"),
                ]),
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