"""Tests for the Kafka client configuration the DLQ replay activities build."""

import pytest

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.settings.kafka import KafkaProfileSettings
from posthog.temporal.dlq_replay.activities import client_kwargs, resolve_topic_profile


def _profile(**overrides) -> KafkaProfileSettings:
    base = {
        "name": "default",
        "hosts": ["broker:9092"],
        "security_protocol": None,
        "sasl_mechanism": None,
        "sasl_user": None,
        "sasl_password": None,
    }
    return KafkaProfileSettings(**{**base, **overrides})


class TestClientKwargs:
    @parameterized.expand(
        [
            ("sasl_ssl", "SASL_SSL", True, True),
            ("sasl_plaintext", "SASL_PLAINTEXT", True, False),
            ("ssl", "SSL", False, True),
            ("plaintext", None, False, False),
        ]
    )
    def test_credentials_and_ssl_context_follow_the_protocol(
        self, _name: str, protocol: str | None, expects_sasl: bool, expects_ssl: bool
    ) -> None:
        kwargs = client_kwargs(
            _profile(
                security_protocol=protocol,
                sasl_mechanism="SCRAM-SHA-512",
                sasl_user="replayer",
                sasl_password="secret",
            )
        )

        assert kwargs["security_protocol"] == (protocol or "PLAINTEXT")
        assert (kwargs["ssl_context"] is not None) == expects_ssl
        if expects_sasl:
            assert kwargs["sasl_mechanism"] == "SCRAM-SHA-512"
            assert kwargs["sasl_plain_username"] == "replayer"
            assert kwargs["sasl_plain_password"] == "secret"
        else:
            assert "sasl_mechanism" not in kwargs


class TestResolveTopicProfile:
    def test_rejects_a_sasl_profile_without_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "posthog.temporal.dlq_replay.activities.get_profile_settings",
            lambda topic: _profile(security_protocol="SASL_SSL"),
        )

        with pytest.raises(ApplicationError) as error:
            resolve_topic_profile("some_dlq_topic")

        assert error.value.non_retryable

    def test_rejects_unconfigured_hosts_outside_dev(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "posthog.temporal.dlq_replay.activities.get_profile_settings",
            lambda topic: _profile(hosts=["kafka:9092"], hosts_configured=False),
        )
        monkeypatch.setattr("posthog.temporal.dlq_replay.activities.settings.DEBUG", False)
        monkeypatch.setattr("posthog.temporal.dlq_replay.activities.settings.TEST", False)

        with pytest.raises(ApplicationError) as error:
            resolve_topic_profile("some_dlq_topic")

        assert error.value.non_retryable
