from contextlib import contextmanager
from typing import cast

from unittest import TestCase, mock
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized

from posthog.kafka_client import routing
from posthog.kafka_client.routing import (
    KafkaClusterProfile,
    _parse_routing_overrides,
    async_producer_scope,
    current_topic_routing,
    flush_all_producers,
    get_producer,
    new_async_producer,
    producer_scope,
    reset_producers,
)
from posthog.kafka_client.topics import (
    KAFKA_APP_METRICS2,
    KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
    KAFKA_DWH_CDP_RAW_TABLE,
    KAFKA_EVENTS_JSON,
    KAFKA_WAREHOUSE_SOURCES_JOBS,
)


@contextmanager
def _mock_kafka_backend():
    """Replace the router's producer factories so no real broker is touched.

    `_build_sync_producer` returns a stable MagicMock per profile (so the
    router's cache behaviour is observable).  `_build_async_producer` returns a
    fresh MagicMock per call with awaitable `flush`/`close` methods.
    """
    sync_producers: dict[KafkaClusterProfile, MagicMock] = {}

    def sync_factory(profile: KafkaClusterProfile) -> MagicMock:
        if profile not in sync_producers:
            sync_producers[profile] = MagicMock(name=f"sync_producer[{profile}]")
        return sync_producers[profile]

    def async_factory(profile: KafkaClusterProfile, loop=None) -> MagicMock:
        producer = MagicMock(name=f"async_producer[{profile}]")
        producer.flush = mock.AsyncMock()
        producer.close = mock.AsyncMock()
        return producer

    with (
        patch.object(routing, "_build_sync_producer", side_effect=sync_factory) as sync_build,
        patch.object(routing, "_build_async_producer", side_effect=async_factory) as async_build,
    ):
        yield sync_build, async_build


class ParseRoutingOverridesTest(TestCase):
    @parameterized.expand(
        [
            ("empty_string", "", {}),
            ("only_whitespace", "   ", {}),
            ("single", "topic_a=default", {"topic_a": KafkaClusterProfile.DEFAULT}),
            (
                "multiple",
                "topic_a=default,topic_b=warehouse_sources",
                {
                    "topic_a": KafkaClusterProfile.DEFAULT,
                    "topic_b": KafkaClusterProfile.WAREHOUSE_SOURCES,
                },
            ),
            (
                "tolerates_whitespace",
                "  topic_a = default , topic_b=cyclotron ",
                {
                    "topic_a": KafkaClusterProfile.DEFAULT,
                    "topic_b": KafkaClusterProfile.CYCLOTRON,
                },
            ),
            (
                "trailing_comma",
                "topic_a=default,",
                {"topic_a": KafkaClusterProfile.DEFAULT},
            ),
        ]
    )
    def test_valid_inputs_parse(self, _name, raw, expected):
        self.assertEqual(_parse_routing_overrides(raw), expected)

    @parameterized.expand(
        [
            ("missing_equals", "topic_a"),
            ("empty_topic", "=default"),
            ("empty_profile", "topic_a="),
        ]
    )
    def test_malformed_entries_raise(self, _name, raw):
        with self.assertRaisesRegex(ValueError, "Malformed KAFKA_TOPIC_ROUTING_OVERRIDES"):
            _parse_routing_overrides(raw)

    def test_unknown_profile_raises(self):
        with self.assertRaisesRegex(ValueError, "Unknown profile 'not_a_profile'"):
            _parse_routing_overrides("topic_a=not_a_profile")


class CurrentTopicRoutingTest(TestCase):
    def test_without_overrides_returns_defaults(self):
        with override_settings(KAFKA_TOPIC_ROUTING_OVERRIDES=""):
            mapping = current_topic_routing()
        self.assertEqual(mapping.get(KAFKA_WAREHOUSE_SOURCES_JOBS), KafkaClusterProfile.WAREHOUSE_SOURCES)
        self.assertEqual(mapping.get(KAFKA_DWH_CDP_RAW_TABLE), KafkaClusterProfile.CYCLOTRON)
        # All Django-produced topics are now explicitly listed; DEFAULT topics resolve to DEFAULT.
        self.assertEqual(mapping.get(KAFKA_APP_METRICS2), KafkaClusterProfile.DEFAULT)

    def test_env_overrides_add_new_topic(self):
        with override_settings(
            KAFKA_TOPIC_ROUTING_OVERRIDES=f"{KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES}=cyclotron"
        ):
            mapping = current_topic_routing()
        self.assertEqual(
            mapping.get(KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES),
            KafkaClusterProfile.CYCLOTRON,
        )
        # Defaults still present.
        self.assertEqual(mapping.get(KAFKA_WAREHOUSE_SOURCES_JOBS), KafkaClusterProfile.WAREHOUSE_SOURCES)

    def test_env_overrides_win_over_defaults(self):
        with override_settings(KAFKA_TOPIC_ROUTING_OVERRIDES=f"{KAFKA_DWH_CDP_RAW_TABLE}=default"):
            mapping = current_topic_routing()
        self.assertEqual(mapping.get(KAFKA_DWH_CDP_RAW_TABLE), KafkaClusterProfile.DEFAULT)


class ResolveAndGetProducerTest(TestCase):
    def setUp(self):
        reset_producers()

    def tearDown(self):
        reset_producers()

    def test_topic_not_in_map_resolves_to_default(self):
        with _mock_kafka_backend() as (sync_build, _):
            producer = get_producer(topic=KAFKA_EVENTS_JSON)
            # Same call via the profile should reuse the cached producer.
            self.assertIs(producer, get_producer(profile=KafkaClusterProfile.DEFAULT))
        sync_build.assert_called_once_with(KafkaClusterProfile.DEFAULT)

    def test_topic_in_map_resolves_to_profile(self):
        with _mock_kafka_backend() as (sync_build, _):
            get_producer(topic=KAFKA_WAREHOUSE_SOURCES_JOBS)
        sync_build.assert_called_once_with(KafkaClusterProfile.WAREHOUSE_SOURCES)

    def test_explicit_profile_wins_over_topic(self):
        # Even though the topic is mapped to WAREHOUSE_SOURCES, an explicit
        # `profile=` argument takes precedence.
        with _mock_kafka_backend() as (sync_build, _):
            get_producer(topic=KAFKA_WAREHOUSE_SOURCES_JOBS, profile=KafkaClusterProfile.CYCLOTRON)
        sync_build.assert_called_once_with(KafkaClusterProfile.CYCLOTRON)

    def test_env_override_routes_to_new_profile(self):
        with (
            override_settings(KAFKA_TOPIC_ROUTING_OVERRIDES=f"{KAFKA_EVENTS_JSON}=warehouse_sources"),
            _mock_kafka_backend() as (sync_build, _),
        ):
            get_producer(topic=KAFKA_EVENTS_JSON)
        sync_build.assert_called_once_with(KafkaClusterProfile.WAREHOUSE_SOURCES)

    def test_get_producer_caches_per_profile(self):
        with _mock_kafka_backend() as (sync_build, _):
            first = get_producer(profile=KafkaClusterProfile.DEFAULT)
            second = get_producer(profile=KafkaClusterProfile.DEFAULT)
        self.assertIs(first, second)
        sync_build.assert_called_once()

    def test_get_producer_returns_distinct_producer_per_profile(self):
        with _mock_kafka_backend() as (sync_build, _):
            default_producer = get_producer(profile=KafkaClusterProfile.DEFAULT)
            cyclotron_producer = get_producer(profile=KafkaClusterProfile.CYCLOTRON)
        self.assertIsNot(default_producer, cyclotron_producer)
        self.assertEqual(sync_build.call_count, 2)


class ProducerScopeTest(TestCase):
    def setUp(self):
        reset_producers()

    def tearDown(self):
        reset_producers()

    def test_flushes_on_success(self):
        with _mock_kafka_backend() as (sync_build, _):
            with producer_scope(profile=KafkaClusterProfile.DEFAULT) as producer:
                pass
        cast(MagicMock, producer).flush.assert_called_once()
        sync_build.assert_called_once_with(KafkaClusterProfile.DEFAULT)

    def test_flushes_on_error(self):
        with _mock_kafka_backend() as (sync_build, _):
            producer = None
            with self.assertRaises(RuntimeError):
                with producer_scope(profile=KafkaClusterProfile.DEFAULT) as p:
                    producer = p
                    raise RuntimeError("boom")
        assert producer is not None
        cast(MagicMock, producer).flush.assert_called_once()

    def test_passes_flush_timeout(self):
        with _mock_kafka_backend():
            with producer_scope(profile=KafkaClusterProfile.DEFAULT, flush_timeout=5) as producer:
                pass
        cast(MagicMock, producer).flush.assert_called_once_with(5)


class AsyncProducerScopeTest(TestCase):
    def test_flushes_and_closes_on_success(self):
        import asyncio

        with _mock_kafka_backend() as (_, async_build):
            captured = {}

            async def run():
                async with async_producer_scope(profile=KafkaClusterProfile.DEFAULT) as p:
                    captured["producer"] = p

            asyncio.run(run())

        producer = cast(MagicMock, captured["producer"])
        producer.flush.assert_awaited_once()
        producer.close.assert_awaited_once()
        async_build.assert_called_once_with(KafkaClusterProfile.DEFAULT)

    def test_closes_on_error_but_does_not_flush(self):
        import asyncio

        with _mock_kafka_backend():
            captured = {}

            async def run():
                async with async_producer_scope(profile=KafkaClusterProfile.DEFAULT) as p:
                    captured["producer"] = p
                    raise RuntimeError("boom")

            with self.assertRaises(RuntimeError):
                asyncio.run(run())

        producer = cast(MagicMock, captured["producer"])
        producer.flush.assert_not_awaited()
        producer.close.assert_awaited_once()


class NewAsyncProducerTest(TestCase):
    def test_returns_fresh_instance_per_call(self):
        with _mock_kafka_backend() as (_, async_build):
            async_build.side_effect = lambda profile, loop: MagicMock(name=f"fresh[{profile}]")
            first = new_async_producer(profile=KafkaClusterProfile.DEFAULT)
            second = new_async_producer(profile=KafkaClusterProfile.DEFAULT)
        self.assertIsNot(first, second)
        self.assertEqual(async_build.call_count, 2)


class FlushAllProducersTest(TestCase):
    def setUp(self):
        reset_producers()

    def tearDown(self):
        reset_producers()

    def test_flushes_every_cached_producer(self):
        with _mock_kafka_backend() as (sync_build, _):
            sync_build.side_effect = lambda profile: MagicMock(name=f"sync[{profile}]")
            default_producer = get_producer(profile=KafkaClusterProfile.DEFAULT)
            warehouse_producer = get_producer(profile=KafkaClusterProfile.WAREHOUSE_SOURCES)

            flush_all_producers(timeout=1.5)

        cast(MagicMock, default_producer).flush.assert_called_once_with(1.5)
        cast(MagicMock, warehouse_producer).flush.assert_called_once_with(1.5)

    def test_no_op_when_no_producers_cached(self):
        # Just verifying no exceptions from an empty cache.
        flush_all_producers(timeout=0.1)
