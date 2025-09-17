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

from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner


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
        self.assertEqual(len(results.results), 2)
        self.assertEqual(results.results[0].event, "event1")
        self.assertEqual(results.results[0].count, 2)
        self.assertEqual(results.results[1].event, "event2")
        self.assertEqual(results.results[1].count, 1)

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
            self.assertEqual(len(response.results), 1)

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
            self.assertEqual(len(response.results), 1)

        with freeze_time(now + timedelta(minutes=59)):
            runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
            response = runner.run()

            assert isinstance(response, CachedTeamTaxonomyQueryResponse)
            self.assertEqual(len(response.results), 1)

        with freeze_time(now + timedelta(minutes=61)):
            runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
            response = runner.run()

            assert isinstance(response, CachedTeamTaxonomyQueryResponse)
            self.assertEqual(len(response.results), 2)

    def test_limit(self):
        now = timezone.now()

        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )

        for i in range(501):
            with freeze_time(now + timedelta(minutes=i)):
                _create_event(
                    event=f"event{i}",
                    distinct_id="person1",
                    team=self.team,
                )

        flush_persons_and_events()

        runner = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery())
        response = runner.run()

        assert isinstance(response, CachedTeamTaxonomyQueryResponse)
        self.assertEqual(len(response.results), 500)

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
        self.assertEqual([result.event for result in response.results], ["$pageview", "did custom thing"])
