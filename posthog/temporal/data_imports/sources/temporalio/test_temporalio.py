import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import Client

from posthog.temporal.common.codec import EncryptionCodec
from posthog.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
from posthog.temporal.data_imports.sources.temporalio.source import TemporalIOSource
from posthog.temporal.data_imports.sources.temporalio.temporalio import FakeSettings, _get_temporal_client


class TestTemporalIOClient:
    def test_fake_settings_satisfies_encryption_codec_contract(self):
        # FakeSettings must expose every attribute EncryptionCodec.from_settings reads
        # (TEST, DEBUG, TEMPORAL_SECRET_KEY, TEMPORAL_FALLBACK_SECRET_KEYS); a missing one raises
        # AttributeError. The 32-byte key clears the prod (TEST=False) length guard.
        codec = EncryptionCodec.from_settings(FakeSettings(TEMPORAL_SECRET_KEY="k" * 32))

        assert isinstance(codec, EncryptionCodec)

    async def test_get_temporal_client_builds_encryption_codec(self):
        config = TemporalIOSourceConfig.from_dict(
            {
                "host": "host",
                "port": "7233",
                "namespace": "namespace",
                "encryption_key": "k" * 32,
                "server_client_root_ca": "ca",
                "client_certificate": "cert",
                "client_private_key": "key",
            }
        )

        with patch.object(Client, "connect", new=AsyncMock(return_value=MagicMock())) as mock_connect:
            await _get_temporal_client(config)

        data_converter = mock_connect.call_args.kwargs["data_converter"]
        assert isinstance(data_converter.payload_codec, EncryptionCodec)


class TestTemporalIONonRetryableErrors:
    def setup_method(self):
        self.source = TemporalIOSource()

    @pytest.mark.parametrize(
        "error_message",
        [
            'RuntimeError: Failed client connect: `get_system_info` call error after connection: Status { code: Unknown, message: "transport error", source: Some(tonic::transport::Error(Transport, hyper::Error(Io, Custom { kind: InvalidData, error: "received fatal alert: UnknownCA" }))) }',
            "received fatal alert: CertificateExpired",
            "received fatal alert: CertificateRevoked",
            "received fatal alert: BadCertificate",
            "received fatal alert: CertificateUnknown",
            "invalid peer certificate: UnknownIssuer",
            "Failed client connect: Server connection error: tonic::transport::Error(Transport, CertificateParseError)",
            'RuntimeError: Failed client connect: invalid target URL: empty host: ":7233"',
            "tonic::transport::Error(Transport, InvalidUri(InvalidUri(InvalidFormat))): invalid target URL: empty host",
        ],
    )
    def test_config_failures_are_non_retryable(self, error_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_message",
        [
            'RuntimeError: Failed client connect: `get_system_info` call error after connection: Status { code: Unauthenticated, message: "Jwt is missing", metadata: MetadataMap { headers: {"www-authenticate": "Bearer realm=\\"https://us-east4.gcp.api.temporal.io/temporal.api.workflowservice.v1.WorkflowService/GetSystemInfo\\"", "content-type": "application/grpc", "server": "temporal"} }, source: None }',
        ],
    )
    def test_authentication_failures_are_non_retryable(self, error_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(pattern in error_message for pattern in non_retryable_errors), (
            f"Expected '{error_message}' to match a non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "error_message",
        [
            "activity Heartbeat timeout",
            'RuntimeError: Failed client connect: `get_system_info` call error after connection: Status { code: Unknown, message: "transport error", source: Some(tonic::transport::Error(Transport, hyper::Error(Io, Os { code: 60, kind: TimedOut, message: "Operation timed out" }))) }',
        ],
    )
    def test_transient_failures_stay_retryable(self, error_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(pattern in error_message for pattern in non_retryable_errors), (
            f"'{error_message}' must not match a non-retryable pattern"
        )
