from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.schema import CachedTeamTaxonomyQueryResponse, TeamTaxonomyQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)
from ee.models.event_definition import EnterpriseEventDefinition


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

    @snapshot_clickhouse_queries
    def test_similarity_search(self):
        _create_person(
            distinct_ids=["person1"],
            properties={"email": "person1@example.com"},
            team=self.team,
        )
        _create_event(
            event="user_signup",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="user_login",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )
        _create_event(
            event="page_view",
            distinct_id="person1",
            properties={"$browser": "Chrome", "$country": "US"},
            team=self.team,
        )

        # Test with a query plan that should match user_signup
        results = TeamTaxonomyQueryRunner(
            team=self.team, query=TeamTaxonomyQuery(plan="show users who signed up over the last month")
        ).calculate()

        self.assertEqual(len(results.results), 3)  # All events should be returned
        self.assertEqual(results.results[0].event, "user_signup")  # Should be first due to similarity
        self.assertIsNotNone(results.results[0].similarity)
        similarity = results.results[0].similarity
        assert similarity is not None  # Type assertion
        self.assertGreater(similarity, 0.1)

        # Test with a query plan that should match page_view
        results = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(plan="show page views")).calculate()

        self.assertEqual(len(results.results), 3)  # All events should be returned
        self.assertEqual(results.results[0].event, "page_view")  # Should be first due to similarity
        self.assertIsNotNone(results.results[0].similarity)
        similarity = results.results[0].similarity
        assert similarity is not None  # Type assertion
        self.assertGreater(similarity, 0.1)

    @snapshot_clickhouse_queries
    def test_similarity_batch_calculation(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        events = ["user_signup", "user_login", "page_view", "button_click", "form_submit"]
        for event in events:
            _create_event(event=event, distinct_id="person1", team=self.team)

        results = TeamTaxonomyQueryRunner(
            team=self.team, query=TeamTaxonomyQuery(plan="user authentication events")
        ).calculate()

        # Should prioritize auth-related events
        first_similarity = results.results[0].similarity
        last_similarity = results.results[-1].similarity
        assert first_similarity is not None and last_similarity is not None
        self.assertGreater(first_similarity, last_similarity)
        self.assertIn(results.results[0].event, ["user_signup", "user_login"])

    @snapshot_clickhouse_queries
    def test_description_similarity(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_event(event="custom_event", distinct_id="person1", team=self.team)

        # Mock enterprise event definition with description
        EnterpriseEventDefinition.objects.create(
            team=self.team, name="custom_event", description="User completed onboarding flow"
        )

        results = TeamTaxonomyQueryRunner(
            team=self.team, query=TeamTaxonomyQuery(plan="onboarding completion")
        ).calculate()

        self.assertEqual(results.results[0].event, "custom_event")
        similarity = results.results[0].similarity
        assert similarity is not None
        self.assertGreater(similarity, 0.1)

    @snapshot_clickhouse_queries
    def test_empty_similarity_inputs(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_event(event="event1", distinct_id="person1", team=self.team)

        # Empty query plan
        results = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(plan="")).calculate()

        self.assertEqual(len(results.results), 1)
        self.assertIsNone(results.results[0].similarity)

        # Very short query
        results = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(plan="a")).calculate()

        self.assertEqual(len(results.results), 1)
        self.assertIsNotNone(results.results[0].similarity)

    @snapshot_clickhouse_queries
    def test_similarity_weights(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        events = [
            ("user_signup", "User signed up for the first time"),
            ("signup", "User created an account"),
            ("new_user", "New user registration"),
        ]
        for event, desc in events:
            _create_event(event=event, distinct_id="person1", team=self.team)
            EnterpriseEventDefinition.objects.create(team=self.team, name=event, description=desc)

        results = TeamTaxonomyQueryRunner(
            team=self.team, query=TeamTaxonomyQuery(plan="new user registration")
        ).calculate()

        # Should consider both name and description similarity
        similarity = results.results[0].similarity
        assert similarity is not None
        self.assertGreater(similarity, 0.5)

    @snapshot_clickhouse_queries
    def test_empty_text_list(self):
        _create_person(distinct_ids=["person1"], team=self.team)
        _create_event(event="event1", distinct_id="person1", team=self.team)

        # Test with empty event list
        results = TeamTaxonomyQueryRunner(team=self.team, query=TeamTaxonomyQuery(plan="test")).calculate()

        self.assertEqual(len(results.results), 1)
        self.assertIsNotNone(results.results[0].similarity)

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
