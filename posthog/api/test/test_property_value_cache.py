from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from posthog.api.property_value_cache import (
    PROPERTY_VALUES_CACHE_TTL,
    cache_property_values,
    get_cached_property_values,
)
from posthog.redis import get_client


class TestPropertyValueCache(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.redis_client = get_client()

    def test_event_property_values_cached_in_redis(self):
        with freeze_time("2020-01-20 20:00:00"):
            _create_event(
                distinct_id="test_user",
                event="test_event",
                team=self.team,
                properties={"test_prop": "value1"},
            )
            _create_event(
                distinct_id="test_user",
                event="test_event",
                team=self.team,
                properties={"test_prop": "value2"},
            )
            _create_event(
                distinct_id="test_user",
                event="test_event",
                team=self.team,
                properties={"test_prop": "value3"},
            )

            # Make request to event property values endpoint
            response = self.client.get(f"/api/projects/{self.team.pk}/events/values/?key=test_prop")

            assert response.status_code == 200
            result = response.json()

            # Verify we got the expected values
            values = {item["name"] for item in result}
            assert "value1" in values
            assert "value2" in values
            assert "value3" in values

            # Verify the values were cached in Redis
            cached_values = get_cached_property_values(
                team_id=self.team.pk, property_type="event", property_key="test_prop"
            )

            assert cached_values is not None
            assert len(cached_values) == 3

            cached_names = {item["name"] for item in cached_values}
            assert cached_names == {"value1", "value2", "value3"}

    def test_person_property_values_cached_in_redis(self):
        with freeze_time("2020-01-20 20:00:00"):
            _create_person(
                distinct_ids=["user1"],
                team=self.team,
                properties={"email": "user1@example.com"},
            )
            _create_person(
                distinct_ids=["user2"],
                team=self.team,
                properties={"email": "user2@example.com"},
            )

            # Make request to person property values endpoint
            response = self.client.get(f"/api/projects/{self.team.pk}/persons/values/?key=email")

            assert response.status_code == 200
            result = response.json()

            # Verify we got the expected values
            assert len(result) > 0
            values = {item["name"] for item in result}
            assert "user1@example.com" in values
            assert "user2@example.com" in values

            # Verify the values were cached in Redis
            cached_values = get_cached_property_values(
                team_id=self.team.pk, property_type="person", property_key="email"
            )

            assert cached_values is not None
            assert len(cached_values) >= 2

            cached_names = {item["name"] for item in cached_values}
            assert "user1@example.com" in cached_names
            assert "user2@example.com" in cached_names

    def test_cached_property_values_have_correct_ttl(self):
        values = [{"name": "test1"}, {"name": "test2"}]

        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_key",
            values=values,
        )

        # Retrieve cached values
        cached = get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="test_key")

        assert cached is not None
        assert cached == values

        # Verify TTL is set correctly (7 days)
        from posthog.api.property_value_cache import _make_cache_key

        cache_key = _make_cache_key(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_key",
        )

        ttl = self.redis_client.ttl(cache_key)
        # TTL should be close to 7 days (604800 seconds)
        # Allow some margin for test execution time
        assert ttl > PROPERTY_VALUES_CACHE_TTL - 10
        assert ttl <= PROPERTY_VALUES_CACHE_TTL

    def test_cache_key_includes_search_value(self):
        values_all = [{"name": "value1"}, {"name": "value2"}]
        values_filtered = [{"name": "value1"}]

        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_prop",
            values=values_all,
        )

        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_prop",
            values=values_filtered,
            search_value="val1",
        )

        # Retrieve both caches - they should be different
        cached_all = get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="test_prop")

        cached_filtered = get_cached_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_prop",
            search_value="val1",
        )

        assert cached_all == values_all
        assert cached_filtered == values_filtered
        assert cached_all != cached_filtered

    def test_cache_key_includes_event_names(self):
        values_all_events = [{"name": "value1"}, {"name": "value2"}]
        values_filtered_events = [{"name": "value1"}]

        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_prop",
            values=values_all_events,
        )

        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_prop",
            values=values_filtered_events,
            event_names=["specific_event"],
        )

        # Retrieve both caches - they should be different
        cached_all = get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="test_prop")

        cached_filtered = get_cached_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="test_prop",
            event_names=["specific_event"],
        )

        assert cached_all == values_all_events
        assert cached_filtered == values_filtered_events
        assert cached_all != cached_filtered
