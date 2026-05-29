from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.core.cache import cache

from posthog.schema import ProductKey

from posthog.models.product_intent.promoted_product_lookup import _cache_key, get_promoted_product_intent


class TestPromotedProductLookup(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.delete(_cache_key(self.team.pk))

    def _create_intent_event(
        self,
        product_key: str,
        intent_context: str = "onboarding product selected - primary",
        timestamp: datetime | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event="user showed product intent",
            distinct_id="user-1",
            properties={"product_key": product_key, "intent_context": intent_context},
            timestamp=timestamp or datetime.now(),
        )

    def test_returns_none_when_no_event_exists(self) -> None:
        assert get_promoted_product_intent(self.team.pk) is None

    def test_returns_product_key_from_primary_intent(self) -> None:
        self._create_intent_event(ProductKey.SESSION_REPLAY.value)
        flush_persons_and_events()

        assert get_promoted_product_intent(self.team.pk) == "session_replay"

    def test_ignores_secondary_intent_context(self) -> None:
        self._create_intent_event(
            ProductKey.SESSION_REPLAY.value,
            intent_context="onboarding product selected - secondary",
        )
        flush_persons_and_events()

        assert get_promoted_product_intent(self.team.pk) is None

    def test_returns_most_recent_primary_intent(self) -> None:
        now = datetime.now()
        self._create_intent_event(ProductKey.PRODUCT_ANALYTICS.value, timestamp=now - timedelta(days=2))
        self._create_intent_event(ProductKey.SESSION_REPLAY.value, timestamp=now - timedelta(days=1))
        self._create_intent_event(ProductKey.WEB_ANALYTICS.value, timestamp=now)
        flush_persons_and_events()

        assert get_promoted_product_intent(self.team.pk) == "web_analytics"

    def test_scopes_by_team(self) -> None:
        other_team = self.organization.teams.create(name="other")
        self._create_intent_event(ProductKey.SESSION_REPLAY.value)
        _create_event(
            team=other_team,
            event="user showed product intent",
            distinct_id="user-other",
            properties={
                "product_key": ProductKey.WEB_ANALYTICS.value,
                "intent_context": "onboarding product selected - primary",
            },
        )
        flush_persons_and_events()

        assert get_promoted_product_intent(self.team.pk) == "session_replay"
        assert get_promoted_product_intent(other_team.pk) == "web_analytics"

    def test_rejects_unknown_product_key(self) -> None:
        self._create_intent_event("not_a_real_product")
        flush_persons_and_events()

        assert get_promoted_product_intent(self.team.pk) is None

    def test_cache_hit_skips_clickhouse(self) -> None:
        self._create_intent_event(ProductKey.SESSION_REPLAY.value)
        flush_persons_and_events()

        # Prime the cache
        assert get_promoted_product_intent(self.team.pk) == "session_replay"

        # Subsequent change in ClickHouse must not be visible until TTL expires
        self._create_intent_event(ProductKey.WEB_ANALYTICS.value)
        flush_persons_and_events()
        assert get_promoted_product_intent(self.team.pk) == "session_replay"

    def test_cache_stores_null_as_empty_string(self) -> None:
        # First call: no event, caches a sentinel so we don't re-query ClickHouse
        assert get_promoted_product_intent(self.team.pk) is None
        assert cache.get(_cache_key(self.team.pk)) == ""
