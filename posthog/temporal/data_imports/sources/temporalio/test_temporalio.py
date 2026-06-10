from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.client import Client

from posthog.temporal.common.codec import EncryptionCodec
from posthog.temporal.data_imports.sources.generated_configs import TemporalIOSourceConfig
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
