import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import snappy
import aiohttp

from posthog.storage.session_recording_v2_object_storage import (
    EncryptedBlockStorage,
    RecordingApiFetchError,
    encrypted_block_storage,
)


class TestEncryptedBlockStorage:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return EncryptedBlockStorage(mock_session, "http://localhost:6740")

    @pytest.fixture
    def client_with_trailing_slash(self, mock_session):
        return EncryptedBlockStorage(mock_session, "http://localhost:6740/")

    def test_init_strips_trailing_slash(self, client_with_trailing_slash):
        assert client_with_trailing_slash.base_url == "http://localhost:6740"

    def test_build_s3_uri_returns_input(self, client):
        block_url = "s3://bucket/key?range=bytes=0-100"
        assert client._build_s3_uri(block_url) == block_url


class TestFetchBlockBytes:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return EncryptedBlockStorage(mock_session, "http://localhost:6740")

    @pytest.mark.asyncio
    async def test_successful_fetch(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"compressed-data")
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.fetch_block_bytes(
            "s3://bucket/key?range=bytes=0-100",
            "session-123",
            1,
        )

        assert result == b"compressed-data"
        mock_session.get.assert_called_once_with(
            "http://localhost:6740/api/projects/1/recordings/session-123/block",
            params={"uri": "s3://bucket/key?range=bytes=0-100"},
        )

    @pytest.mark.asyncio
    async def test_404_raises_error(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(RecordingApiFetchError, match="Block not found"):
            await client.fetch_block_bytes(
                "s3://bucket/key?range=bytes=0-100",
                "session-123",
                1,
            )

    @pytest.mark.asyncio
    async def test_client_error_raises_error(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=500,
            )
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(RecordingApiFetchError, match="Failed to fetch block from Recording API"):
            await client.fetch_block_bytes(
                "s3://bucket/key?range=bytes=0-100",
                "session-123",
                1,
            )


class TestFetchBlock:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return EncryptedBlockStorage(mock_session, "http://localhost:6740")

    @pytest.mark.asyncio
    async def test_successful_fetch_and_decompress(self, client, mock_session):
        original_content = '{"type": 3, "data": {}}'
        compressed_content = snappy.compress(original_content.encode("utf-8"))

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=compressed_content)
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.fetch_block(
            "s3://bucket/key?range=bytes=0-100",
            "session-123",
            1,
        )

        assert result == original_content

    @pytest.mark.asyncio
    async def test_strips_trailing_newlines(self, client, mock_session):
        original_content = '{"type": 3, "data": {}}\n\n'
        compressed_content = snappy.compress(original_content.encode("utf-8"))

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=compressed_content)
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        result = await client.fetch_block(
            "s3://bucket/key?range=bytes=0-100",
            "session-123",
            1,
        )

        assert result == '{"type": 3, "data": {}}'

    @pytest.mark.asyncio
    async def test_decompress_error_raises_error(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"not-valid-snappy-data")
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(RecordingApiFetchError, match="Failed to decompress block"):
            await client.fetch_block(
                "s3://bucket/key?range=bytes=0-100",
                "session-123",
                1,
            )

    @pytest.mark.asyncio
    async def test_propagates_fetch_error(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.get = MagicMock(return_value=mock_response)

        with pytest.raises(RecordingApiFetchError, match="Block not found"):
            await client.fetch_block(
                "s3://bucket/key?range=bytes=0-100",
                "session-123",
                1,
            )


class TestDeleteRecording:
    @pytest.fixture
    def mock_session(self):
        return MagicMock(spec=aiohttp.ClientSession)

    @pytest.fixture
    def client(self, mock_session):
        return EncryptedBlockStorage(mock_session, "http://localhost:6740")

    @pytest.mark.asyncio
    async def test_successful_delete(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.delete = MagicMock(return_value=mock_response)

        result = await client.delete_recording("session-123", 1)

        assert result is True
        mock_session.delete.assert_called_once_with("http://localhost:6740/api/projects/1/recordings/session-123")

    @pytest.mark.asyncio
    async def test_not_found_returns_false(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.delete = MagicMock(return_value=mock_response)

        result = await client.delete_recording("session-123", 1)

        assert result is False

    @pytest.mark.asyncio
    async def test_client_error_raises_error(self, client, mock_session):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=500,
            )
        )
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session.delete = MagicMock(return_value=mock_response)

        with pytest.raises(RecordingApiFetchError, match="Failed to delete recording"):
            await client.delete_recording("session-123", 1)


class TestEncryptedBlockStorageContextManager:
    @pytest.mark.asyncio
    async def test_raises_error_when_url_not_configured(self):
        with patch("posthog.storage.session_recording_v2_object_storage.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = None

            with pytest.raises(RuntimeError, match="RECORDING_API_URL is not configured"):
                async with encrypted_block_storage():
                    pass

    @pytest.mark.asyncio
    async def test_raises_error_when_url_is_empty_string(self):
        with patch("posthog.storage.session_recording_v2_object_storage.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = ""

            with pytest.raises(RuntimeError, match="RECORDING_API_URL is not configured"):
                async with encrypted_block_storage():
                    pass

    @pytest.mark.asyncio
    async def test_creates_client_with_configured_url(self):
        with patch("posthog.storage.session_recording_v2_object_storage.settings") as mock_settings:
            mock_settings.RECORDING_API_URL = "http://test-api:8080"

            with patch(
                "posthog.storage.session_recording_v2_object_storage.aiohttp.ClientSession"
            ) as mock_client_session:
                mock_session = AsyncMock()
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_client_session.return_value = mock_session

                async with encrypted_block_storage() as client:
                    assert client.base_url == "http://test-api:8080"
                    assert client.session == mock_session

                mock_client_session.assert_called_once()
                call_kwargs = mock_client_session.call_args[1]
                assert call_kwargs["timeout"].total == 30
                assert call_kwargs["timeout"].connect == 5
