"""Tests for `posthog/settings/kafka.py` — the per-profile Kafka settings module."""

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.kafka_client.profiles import KafkaClusterProfile
from posthog.settings import kafka as kafka_settings


class PerProfileEnvResolutionTest(TestCase):
    """`_env_for` walks profile → legacy-profile → default → legacy-default."""

    def _run_with_env(self, env: dict[str, str]):
        """Helper: run a function under a patched os.environ."""
        return patch.dict("os.environ", env, clear=True)

    def test_profile_specific_new_name_wins(self):
        with self._run_with_env(
            {
                "KAFKA_WAREHOUSE_SOURCES_HOSTS": "new-profile-broker:9092",
                "KAFKA_DEFAULT_HOSTS": "new-default-broker:9092",
                "KAFKA_HOSTS": "legacy-default-broker:9092",
            }
        ):
            assert kafka_settings._env_for("warehouse_sources", "HOSTS") == "new-profile-broker:9092"

    def test_default_new_name_wins_over_default_legacy(self):
        with self._run_with_env(
            {
                "KAFKA_DEFAULT_HOSTS": "new-default-broker:9092",
                "KAFKA_HOSTS": "legacy-default-broker:9092",
            }
        ):
            assert kafka_settings._env_for("warehouse_sources", "HOSTS") == "new-default-broker:9092"

    def test_default_legacy_as_last_resort(self):
        with self._run_with_env({"KAFKA_HOSTS": "legacy-default-broker:9092"}):
            assert kafka_settings._env_for("warehouse_sources", "HOSTS") == "legacy-default-broker:9092"

    def test_default_profile_does_not_escalate_to_itself(self):
        """A default-profile lookup should only consider default-profile envs."""
        with self._run_with_env({"KAFKA_WAREHOUSE_SOURCES_HOSTS": "not-for-default:9092"}):
            assert kafka_settings._env_for("default", "HOSTS") is None

    def test_kafka_url_legacy_alias_for_hosts(self):
        # KAFKA_URL is the oldest legacy name; it should still be honoured.
        with self._run_with_env({"KAFKA_URL": "broker-from-url:9092"}):
            assert kafka_settings._env_for("default", "HOSTS") == "broker-from-url:9092"

    def test_empty_string_treated_as_unset(self):
        with self._run_with_env({"KAFKA_DEFAULT_HOSTS": ""}):
            assert kafka_settings._env_for("default", "HOSTS") is None

    def test_returns_none_when_nothing_set(self):
        with self._run_with_env({}):
            assert kafka_settings._env_for("cyclotron", "HOSTS") is None


class ResolveProducerSettingsTest(TestCase):
    def test_defaults_for_default_profile_are_empty(self):
        with patch.dict("os.environ", {}, clear=True):
            assert kafka_settings._resolve_producer_settings("default") == {}

    def test_warehouse_sources_gets_code_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = kafka_settings._resolve_producer_settings("warehouse_sources")
        assert settings == {"acks": "all", "enable_idempotence": True}

    def test_env_override_wins_over_code_default(self):
        with patch.dict(
            "os.environ",
            {"KAFKA_WAREHOUSE_SOURCES_PRODUCER_ENABLE_IDEMPOTENCE": "false"},
            clear=True,
        ):
            settings = kafka_settings._resolve_producer_settings("warehouse_sources")
        assert not settings["enable_idempotence"]
        assert settings["acks"] == "all"  # still from code default

    def test_all_warpstream_knobs_wired(self):
        with patch.dict(
            "os.environ",
            {
                "KAFKA_CYCLOTRON_PRODUCER_CLIENT_ID": "warpstream-cyclo",
                "KAFKA_CYCLOTRON_PRODUCER_BATCH_SIZE": "100000",
                "KAFKA_CYCLOTRON_PRODUCER_LINGER_MS": "20",
                "KAFKA_CYCLOTRON_PRODUCER_MAX_REQUEST_SIZE": "6000000",
                "KAFKA_CYCLOTRON_PRODUCER_METADATA_MAX_AGE_MS": "15000",
                "KAFKA_CYCLOTRON_PRODUCER_MAX_IN_FLIGHT_REQUESTS_PER_CONNECTION": "1000000",
                "KAFKA_CYCLOTRON_PRODUCER_BUFFER_MEMORY": "1073741824",
                "KAFKA_CYCLOTRON_PRODUCER_TOPIC_METADATA_REFRESH_INTERVAL_MS": "60000",
                "KAFKA_CYCLOTRON_PRODUCER_QUEUE_BUFFERING_MAX_MESSAGES": "1000000",
                "KAFKA_CYCLOTRON_PRODUCER_STICKY_PARTITIONING_LINGER_MS": "25",
                "KAFKA_CYCLOTRON_PRODUCER_ACKS": "all",
                "KAFKA_CYCLOTRON_PRODUCER_ENABLE_IDEMPOTENCE": "true",
                "KAFKA_CYCLOTRON_PRODUCER_COMPRESSION_TYPE": "gzip",
                "KAFKA_CYCLOTRON_PRODUCER_PARTITIONER": "murmur2_random",
            },
            clear=True,
        ):
            settings = kafka_settings._resolve_producer_settings("cyclotron")
        assert settings["client_id"] == "warpstream-cyclo"
        assert settings["batch_size"] == 100000
        assert settings["linger_ms"] == 20
        assert settings["max_request_size"] == 6000000
        assert settings["metadata_max_age_ms"] == 15000
        assert settings["max_in_flight_requests_per_connection"] == 1000000
        assert settings["buffer_memory"] == 1073741824
        assert settings["topic_metadata_refresh_interval_ms"] == 60000
        assert settings["queue_buffering_max_messages"] == 1000000
        assert settings["sticky_partitioning_linger_ms"] == 25
        assert settings["acks"] == "all"
        assert settings["enable_idempotence"]
        assert settings["compression_type"] == "gzip"
        assert settings["partitioner"] == "murmur2_random"

    def test_acks_numeric_parsed_as_int(self):
        with patch.dict("os.environ", {"KAFKA_DEFAULT_PRODUCER_ACKS": "1"}, clear=True):
            settings = kafka_settings._resolve_producer_settings("default")
        assert settings["acks"] == 1

    def test_acks_non_numeric_kept_as_string(self):
        with patch.dict("os.environ", {"KAFKA_DEFAULT_PRODUCER_ACKS": "all"}, clear=True):
            settings = kafka_settings._resolve_producer_settings("default")
        assert settings["acks"] == "all"

    def test_default_profile_producer_tuning_inherited(self):
        """Profile without its own tuning should inherit from KAFKA_DEFAULT_PRODUCER_*."""
        with patch.dict(
            "os.environ",
            {"KAFKA_DEFAULT_PRODUCER_BATCH_SIZE": "50000"},
            clear=True,
        ):
            settings = kafka_settings._resolve_producer_settings("cyclotron")
        assert settings["batch_size"] == 50000

    def test_profile_tuning_wins_over_default_tuning(self):
        with patch.dict(
            "os.environ",
            {
                "KAFKA_DEFAULT_PRODUCER_BATCH_SIZE": "50000",
                "KAFKA_CYCLOTRON_PRODUCER_BATCH_SIZE": "999999",
            },
            clear=True,
        ):
            settings = kafka_settings._resolve_producer_settings("cyclotron")
        assert settings["batch_size"] == 999999

    def test_legacy_kafka_producer_name_still_honoured(self):
        """`KAFKA_PRODUCER_BATCH_SIZE` (no profile prefix) is a legacy default alias."""
        with patch.dict("os.environ", {"KAFKA_PRODUCER_BATCH_SIZE": "77777"}, clear=True):
            settings = kafka_settings._resolve_producer_settings("warehouse_sources")
        assert settings["batch_size"] == 77777


class ResolveProfileTest(TestCase):
    def test_default_profile_falls_back_to_kafka9092(self):
        with patch.dict("os.environ", {}, clear=True):
            profile = kafka_settings._resolve_profile("default")
        assert profile.hosts == ["kafka:9092"]

    def test_non_default_profile_inherits_dev_fallback_without_env(self):
        """Every profile falls back to the dev-local broker when no env is set."""
        with patch.dict("os.environ", {}, clear=True):
            profile = kafka_settings._resolve_profile("cyclotron")
        assert profile.hosts == ["kafka:9092"]

    def test_resolves_full_profile_settings(self):
        with patch.dict(
            "os.environ",
            {
                "KAFKA_WAREHOUSE_SOURCES_HOSTS": "broker-1:9092,broker-2:9092",
                "KAFKA_WAREHOUSE_SOURCES_SECURITY_PROTOCOL": "SASL_SSL",
                "KAFKA_WAREHOUSE_SOURCES_SASL_MECHANISM": "SCRAM-SHA-512",
                "KAFKA_WAREHOUSE_SOURCES_SASL_USER": "warehouser",
                "KAFKA_WAREHOUSE_SOURCES_SASL_PASSWORD": "secret",
            },
            clear=True,
        ):
            profile = kafka_settings._resolve_profile("warehouse_sources")
        assert profile.hosts == ["broker-1:9092", "broker-2:9092"]
        assert profile.security_protocol == "SASL_SSL"
        assert profile.sasl_mechanism == "SCRAM-SHA-512"
        assert profile.sasl_user == "warehouser"
        assert profile.sasl_password == "secret"
        # Code default for warehouse_sources is still present.
        assert profile.producer_settings["acks"] == "all"


class KafkaProfilesMapTest(TestCase):
    def test_contains_an_entry_per_enum_value(self):
        expected_names = {p.value for p in KafkaClusterProfile}
        assert set(kafka_settings.KAFKA_PROFILES.keys()) == expected_names

    @parameterized.expand(
        [
            (KafkaClusterProfile.DEFAULT,),
            (KafkaClusterProfile.WAREHOUSE_SOURCES,),
            (KafkaClusterProfile.CYCLOTRON,),
        ]
    )
    def test_each_profile_is_a_frozen_KafkaProfileSettings(self, profile):
        settings = kafka_settings.KAFKA_PROFILES[profile.value]
        assert isinstance(settings, kafka_settings.KafkaProfileSettings)
        assert settings.name == profile.value


class ParseKafkaHostsTest(TestCase):
    @parameterized.expand(
        [
            ("simple", "broker:9092", ["broker:9092"]),
            ("multiple", "b1:9092,b2:9092,b3:9092", ["b1:9092", "b2:9092", "b3:9092"]),
            ("with_scheme", "kafka://broker:9092", ["broker:9092"]),
            ("empty_segments_dropped", "b1:9092,,b2:9092", ["b1:9092", "b2:9092"]),
            ("empty_string", "", []),
            ("none_like", None, []),
        ]
    )
    def test_parsing(self, _name, raw, expected):
        assert kafka_settings._parse_kafka_hosts(raw or "") == expected
