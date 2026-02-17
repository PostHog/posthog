from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.api.property_value_cache import (
    PROPERTY_VALUES_CACHE_TTL,
    PROPERTY_VALUES_REFRESH_COOLDOWN,
    _make_cache_key,
    cache_property_values,
    get_cached_property_values,
    is_refresh_on_cooldown,
    set_refresh_cooldown,
)
from posthog.redis import get_client
from posthog.tasks.property_value_cache import (
    refresh_event_property_values_cache,
    refresh_person_property_values_cache,
    run_event_property_query_and_cache,
    run_person_property_query_and_cache,
)


class TestPropertyValueCache(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.redis_client = get_client()

    # ------------------------------------------------------------------
    # Unit tests: cooldown helpers
    # ------------------------------------------------------------------

    def test_is_refresh_on_cooldown_returns_false_when_not_set(self):
        assert not is_refresh_on_cooldown(team_id=self.team.pk, property_type="event", property_key="color")

    def test_set_refresh_cooldown_makes_is_refresh_on_cooldown_true(self):
        set_refresh_cooldown(team_id=self.team.pk, property_type="event", property_key="color")
        assert is_refresh_on_cooldown(team_id=self.team.pk, property_type="event", property_key="color")

    def test_cooldown_key_has_correct_ttl(self):
        set_refresh_cooldown(team_id=self.team.pk, property_type="event", property_key="color")
        cooldown_key = _make_cache_key(self.team.pk, "event", "color") + ":refreshing"
        ttl = self.redis_client.ttl(cooldown_key)
        assert ttl > PROPERTY_VALUES_REFRESH_COOLDOWN - 5
        assert ttl <= PROPERTY_VALUES_REFRESH_COOLDOWN

    def test_cooldown_is_scoped_to_parameters(self):
        set_refresh_cooldown(team_id=self.team.pk, property_type="event", property_key="color")
        # Different key, same team — should not be on cooldown
        assert not is_refresh_on_cooldown(team_id=self.team.pk, property_type="event", property_key="size")
        # Same key, different property type
        assert not is_refresh_on_cooldown(team_id=self.team.pk, property_type="person", property_key="color")

    # ------------------------------------------------------------------
    # Unit tests: value caching helpers
    # ------------------------------------------------------------------

    def test_cached_property_values_have_correct_ttl(self):
        values = [{"name": "test1"}, {"name": "test2"}]
        cache_property_values(team_id=self.team.pk, property_type="event", property_key="test_key", values=values)

        cached = get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="test_key")
        assert cached == values

        cache_key = _make_cache_key(team_id=self.team.pk, property_type="event", property_key="test_key")
        ttl = self.redis_client.ttl(cache_key)
        assert ttl > PROPERTY_VALUES_CACHE_TTL - 10
        assert ttl <= PROPERTY_VALUES_CACHE_TTL

    def test_cache_key_includes_search_value(self):
        values_all = [{"name": "value1"}, {"name": "value2"}]
        values_filtered = [{"name": "value1"}]

        cache_property_values(team_id=self.team.pk, property_type="event", property_key="prop", values=values_all)
        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="prop",
            values=values_filtered,
            search_value="val1",
        )

        assert (
            get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="prop") == values_all
        )
        assert (
            get_cached_property_values(
                team_id=self.team.pk, property_type="event", property_key="prop", search_value="val1"
            )
            == values_filtered
        )

    def test_cache_key_includes_event_names(self):
        values_all = [{"name": "value1"}, {"name": "value2"}]
        values_filtered = [{"name": "value1"}]

        cache_property_values(team_id=self.team.pk, property_type="event", property_key="prop", values=values_all)
        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="prop",
            values=values_filtered,
            event_names=["specific_event"],
        )

        assert (
            get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="prop") == values_all
        )
        assert (
            get_cached_property_values(
                team_id=self.team.pk, property_type="event", property_key="prop", event_names=["specific_event"]
            )
            == values_filtered
        )

    # ------------------------------------------------------------------
    # API: cache miss → live query → refreshing: false
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("event", "test_prop", "/events/values/"),
            ("person", "email", "/persons/values/"),
        ]
    )
    def test_cache_miss_returns_refreshing_false(self, property_type, key, url_suffix):
        with freeze_time("2020-01-20 20:00:00"):
            if property_type == "event":
                _create_event(
                    distinct_id="u",
                    event="e",
                    team=self.team,
                    properties={key: "live_value"},
                )
                flush_persons_and_events()
            else:
                _create_person(distinct_ids=["u"], team=self.team, properties={key: "live_value"})
                flush_persons_and_events()

            with patch("time.sleep"):
                response = self.client.get(f"/api/projects/{self.team.pk}{url_suffix}?key={key}")

        assert response.status_code == 200
        data = response.json()
        assert data["refreshing"] is False
        names = {item["name"] for item in data["results"]}
        assert "live_value" in names

    # ------------------------------------------------------------------
    # API: cache hit → refresh triggered → refreshing: true
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("event", "color", "/events/values/", [{"name": "cached_val"}], refresh_event_property_values_cache),
            (
                "person",
                "plan",
                "/persons/values/",
                [{"name": "cached_val", "count": 1}],
                refresh_person_property_values_cache,
            ),
        ]
    )
    def test_cache_hit_without_cooldown_returns_refreshing_true_and_triggers_refresh(
        self, property_type, key, url_suffix, cached_values, refresh_task
    ):
        cache_property_values(team_id=self.team.pk, property_type=property_type, property_key=key, values=cached_values)

        with patch.object(refresh_task, "delay", return_value=None) as mock_delay:
            response = self.client.get(f"/api/projects/{self.team.pk}{url_suffix}?key={key}")

        assert response.status_code == 200
        assert response.json() == {"results": cached_values, "refreshing": True}
        mock_delay.assert_called_once()

    # ------------------------------------------------------------------
    # API: cache hit on cooldown → no refresh → refreshing: false
    # ------------------------------------------------------------------

    @parameterized.expand(
        [
            ("event", "color", "/events/values/", [{"name": "cached_val"}], refresh_event_property_values_cache),
            (
                "person",
                "plan",
                "/persons/values/",
                [{"name": "cached_val", "count": 1}],
                refresh_person_property_values_cache,
            ),
        ]
    )
    def test_cache_hit_on_cooldown_returns_refreshing_false_and_skips_refresh(
        self, property_type, key, url_suffix, cached_values, refresh_task
    ):
        cache_property_values(team_id=self.team.pk, property_type=property_type, property_key=key, values=cached_values)
        set_refresh_cooldown(team_id=self.team.pk, property_type=property_type, property_key=key)

        with patch.object(refresh_task, "delay") as mock_delay:
            response = self.client.get(f"/api/projects/{self.team.pk}{url_suffix}?key={key}")

        assert response.status_code == 200
        assert response.json() == {"results": cached_values, "refreshing": False}
        mock_delay.assert_not_called()

    # ------------------------------------------------------------------
    # API: second request after refresh completes stops showing refreshing
    # ------------------------------------------------------------------

    def test_event_second_request_after_refresh_returns_refreshing_false(self):
        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="color",
            values=[{"name": "old_value"}],
        )

        # First request: cache hit, no cooldown → triggers refresh
        with patch.object(refresh_event_property_values_cache, "delay", return_value=None):
            first = self.client.get(f"/api/projects/{self.team.pk}/events/values/?key=color")
        assert first.json()["refreshing"] is True

        # Cooldown is now set; simulate background task completing with fresh data
        cache_property_values(
            team_id=self.team.pk,
            property_type="event",
            property_key="color",
            values=[{"name": "fresh_value"}],
        )

        # Second request: cooldown still active → no new refresh, fresh data served
        with patch.object(refresh_event_property_values_cache, "delay") as mock_delay:
            second = self.client.get(f"/api/projects/{self.team.pk}/events/values/?key=color")
        assert second.json() == {"results": [{"name": "fresh_value"}], "refreshing": False}
        mock_delay.assert_not_called()

    # ------------------------------------------------------------------
    # API: background refresh actually updates the cache
    # ------------------------------------------------------------------

    def test_event_background_refresh_updates_cache(self):
        # Cache assertions must be inside freeze_time: fakeredis records expiry
        # relative to the frozen clock, so GET outside freeze_time sees the key
        # as expired (real-time 2026 > frozen-time + 7 days).
        with freeze_time("2020-01-20 20:00:00"):
            _create_event(distinct_id="u", event="e", team=self.team, properties={"color": "db_value"})
            flush_persons_and_events()

            cache_property_values(
                team_id=self.team.pk,
                property_type="event",
                property_key="color",
                values=[{"name": "old_cached_value"}],
            )

            with (
                patch.object(
                    refresh_event_property_values_cache,
                    "delay",
                    side_effect=run_event_property_query_and_cache,
                ),
                patch("time.sleep"),
            ):
                response = self.client.get(f"/api/projects/{self.team.pk}/events/values/?key=color")

            updated = get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="color")
            assert updated is not None
            assert {"name": "db_value"} in updated

        assert response.status_code == 200
        assert response.json()["results"] == [{"name": "old_cached_value"}]
        assert response.json()["refreshing"] is True

    def test_person_background_refresh_updates_cache(self):
        with freeze_time("2020-01-20 20:00:00"):
            _create_person(distinct_ids=["u1"], team=self.team, properties={"plan": "db_value"})

            cache_property_values(
                team_id=self.team.pk,
                property_type="person",
                property_key="plan",
                values=[{"name": "old_cached_value", "count": 1}],
            )

            with (
                patch.object(
                    refresh_person_property_values_cache,
                    "delay",
                    side_effect=run_person_property_query_and_cache,
                ),
                patch("time.sleep"),
            ):
                response = self.client.get(f"/api/projects/{self.team.pk}/persons/values/?key=plan")

            updated = get_cached_property_values(team_id=self.team.pk, property_type="person", property_key="plan")
            assert updated is not None
            assert any(item["name"] == "db_value" for item in updated)

        assert response.status_code == 200
        assert response.json()["results"] == [{"name": "old_cached_value", "count": 1}]
        assert response.json()["refreshing"] is True

    # ------------------------------------------------------------------
    # API: values are cached after a live query (cache miss path)
    # ------------------------------------------------------------------

    def test_event_property_values_cached_after_live_query(self):
        with freeze_time("2020-01-20 20:00:00"):
            for val in ("value1", "value2", "value3"):
                _create_event(distinct_id="u", event="e", team=self.team, properties={"test_prop": val})
            flush_persons_and_events()

            with patch("time.sleep"):
                response = self.client.get(f"/api/projects/{self.team.pk}/events/values/?key=test_prop")

            # Cache check must be inside freeze_time to avoid fakeredis TTL expiry
            # (fakeredis computes expiry relative to the frozen clock)
            cached = get_cached_property_values(team_id=self.team.pk, property_type="event", property_key="test_prop")
            assert cached is not None
            assert {item["name"] for item in cached} == {"value1", "value2", "value3"}

        assert response.status_code == 200
        data = response.json()
        assert data["refreshing"] is False
        names = {item["name"] for item in data["results"]}
        assert names == {"value1", "value2", "value3"}

    def test_person_property_values_cached_after_live_query(self):
        with freeze_time("2020-01-20 20:00:00"):
            _create_person(distinct_ids=["u1"], team=self.team, properties={"email": "u1@example.com"})
            _create_person(distinct_ids=["u2"], team=self.team, properties={"email": "u2@example.com"})

            with patch("time.sleep"):
                response = self.client.get(f"/api/projects/{self.team.pk}/persons/values/?key=email")

            cached = get_cached_property_values(team_id=self.team.pk, property_type="person", property_key="email")
            assert cached is not None
            assert any(item["name"] == "u1@example.com" for item in cached)

        assert response.status_code == 200
        data = response.json()
        assert data["refreshing"] is False
        names = {item["name"] for item in data["results"]}
        assert "u1@example.com" in names
        assert "u2@example.com" in names
