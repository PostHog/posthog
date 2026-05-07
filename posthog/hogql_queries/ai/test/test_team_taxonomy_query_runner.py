from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from django.test import override_settings
from django.utils import timezone

from posthog.schema import CachedTeamTaxonomyQueryResponse, TeamTaxonomyQuery

from posthog.hogql_queries.ai.team_taxonomy_query_runner import WELL_KNOWN_EVENT_NAMES, TeamTaxonomyQueryRunner


@override_settings(IN_UNIT_TESTING=True)
class TestTeamTaxonomyQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_taxonomy_query_runner(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event2",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="event1",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )

        results = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery()).calculate()
        # CH results + well-known events appended on last page
        self.assertEqual(results.results[0].event, "event1")
        self.assertEqual(results.results[0].count, 2)
        self.assertEqual(results.results[1].event, "event2")
        self.assertEqual(results.results[1].count, 1)
        self.assertFalse(results.hasMore)
        self.assertEqual(results.limit, 500)
        self.assertEqual(results.offset, 0)

        # Well-known events are appended with count=0
        well_known_in_results = [r for r in results.results if r.count == 0]
        self.assertEqual(len(well_known_in_results), len(WELL_KNOWN_EVENT_NAMES))
        for item in well_known_in_results:
            self.assertIn(item.event, WELL_KNOWN_EVENT_NAMES)

    def test_caching(self):
        now = timezone.now()

        with freeze_time(now):
            _create_person(
                distinct_ids=["person1"],
                properties={"email": "person1@example.com"},
                team=self.team,
            )
            _create_event(
                event="event1",
                distinct_id="person1",
                team=self.team,
            )

            runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
            response = runner.run()

            assert isinstance(response, CachedTeamTaxonomyQueryResponse)
            # 1 CH result + well-known events
            self.assertEqual(len(response.results), 1 + len(WELL_KNOWN_EVENT_NAMES))

            key = response.cache_key
            _create_event(
                event="event2",
                distinct_id="person1",
                team=self.team,
            )
            flush_persons_and_events()

            runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
            response = runner.run()

            assert isinstance(response, CachedTeamTaxonomyQueryResponse)
            self.assertEqual(response.cache_key, key)
            # Cached: still 1 CH result + well-known events
            self.assertEqual(len(response.results), 1 + len(WELL_KNOWN_EVENT_NAMES))

        with freeze_time(now + timedelta(minutes=59)):
            runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
            response = runner.run()

            assert isinstance(response, CachedTeamTaxonomyQueryResponse)
            self.assertEqual(len(response.results), 1 + len(WELL_KNOWN_EVENT_NAMES))

        with freeze_time(now + timedelta(minutes=61)):
            runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
            response = runner.run()

            assert isinstance(response, CachedTeamTaxonomyQueryResponse)
            # After cache expiry: 2 CH results + well-known events
            self.assertEqual(len(response.results), 2 + len(WELL_KNOWN_EVENT_NAMES))

    def test_limit(self):
        now = timezone.now()

        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        for i in range(501):
            _create_event(
                event=f"event{i}",
                distinct_id="person1",
                team=self.team,
                timestamp=now + timedelta(minutes=i),
            )

        flush_persons_and_events()

        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        # hasMore=True, so no well-known events appended
        self.assertEqual(len(response.results), 500)
        self.assertTrue(response.hasMore)

    def test_pagination_with_limit_and_offset(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        for i in range(10):
            _create_event(
                event=f"event{i}",
                distinct_id="person1",
                team=self.team,
            )

        flush_persons_and_events()

        # First page - hasMore=True, no well-known events appended
        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(limit=5, offset=0))
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        self.assertEqual(len(response.results), 5)
        self.assertTrue(response.hasMore)
        self.assertEqual(response.limit, 5)
        self.assertEqual(response.offset, 0)

        first_page_events = {r.event for r in response.results}

        # Second page - hasMore=False, well-known events appended
        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(limit=5, offset=5))
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        self.assertFalse(response.hasMore)
        self.assertEqual(response.limit, 5)
        self.assertEqual(response.offset, 5)

        # No overlap between pages for CH results
        ch_second_page = {r.event for r in response.results if r.count > 0}
        self.assertEqual(len(first_page_events & ch_second_page), 0)
        # All 10 custom events covered across pages
        self.assertEqual(len(first_page_events | ch_second_page), 10)

        # Well-known events with count=0 are also present on last page
        well_known_on_last_page = [r for r in response.results if r.count == 0]
        self.assertGreater(len(well_known_on_last_page), 0)

    def test_events_not_useful_for_llm_ignored(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        for _i in range(2):
            _create_event(
                event="$pageview",
                distinct_id="person1",
                properties={"$browser": "Chrome", "$country": "US"},
                team=self.team,
            )
        _create_event(
            event="did custom thing",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        # Events below should have `ignored_in_assistant`
        _create_event(
            event="$pageleave",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="$autocapture",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="$feature_flag_called",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )

        flush_persons_and_events()

        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        # $pageview has count > 0 from CH; "did custom thing" has count > 0
        ch_results = [r for r in response.results if r.count > 0]
        self.assertEqual([r.event for r in ch_results], ["$pageview", "did custom thing"])

        # Ignored events are NOT in results
        all_event_names = {r.event for r in response.results}
        self.assertNotIn("$pageleave", all_event_names)
        self.assertNotIn("$autocapture", all_event_names)
        self.assertNotIn("$feature_flag_called", all_event_names)

    def test_well_known_events_not_duplicated(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        # Create a well-known event that also appears in CH
        _create_event(
            event="$pageview",
            distinct_id="person1",
            team=self.team,
        )

        flush_persons_and_events()

        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        # $pageview should appear exactly once (from CH, not duplicated)
        pageview_results = [r for r in response.results if r.event == "$pageview"]
        self.assertEqual(len(pageview_results), 1)
        self.assertEqual(pageview_results[0].count, 1)

    def test_well_known_events_only_on_last_page(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        for i in range(10):
            _create_event(
                event=f"event{i}",
                distinct_id="person1",
                team=self.team,
            )

        flush_persons_and_events()

        # First page: hasMore=True, no well-known events
        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(limit=5, offset=0))
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        self.assertTrue(response.hasMore)
        zero_count = [r for r in response.results if r.count == 0]
        self.assertEqual(len(zero_count), 0)

        # Last page: hasMore=False, well-known events appended
        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(limit=5, offset=5))
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        self.assertFalse(response.hasMore)
        zero_count = [r for r in response.results if r.count == 0]
        self.assertEqual(len(zero_count), len(WELL_KNOWN_EVENT_NAMES))
