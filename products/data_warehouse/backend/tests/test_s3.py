import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.data_warehouse.backend.s3 import aget_s3_client, get_size_of_folder


class TestAgetS3Client(SimpleTestCase):
    @override_settings(USE_LOCAL_SETUP=False)
    def test_fresh_instance_closes_the_full_s3creator_not_just_the_general_client(self) -> None:
        # With region caching on (the s3fs default), a fresh_instance client that touches a bucket
        # outside its default region opens a second, region-specific aiobotocore client that only
        # _s3creator tracks (S3BucketRegionCache.get_bucket_client). Closing _s3 alone would leak it.
        fake_s3 = MagicMock()
        fake_s3.set_session = AsyncMock()
        fake_s3._s3 = MagicMock()
        fake_s3._s3.close = AsyncMock()
        fake_s3._s3creator = MagicMock()
        fake_s3._s3creator.__aexit__ = AsyncMock()

        async def run() -> None:
            with patch("products.data_warehouse.backend.s3.s3fs.S3FileSystem", return_value=fake_s3):
                async with aget_s3_client(fresh_instance=True) as s3:
                    assert s3 is fake_s3

        asyncio.run(run())

        fake_s3._s3creator.__aexit__.assert_awaited_once_with(None, None, None)
        fake_s3._s3.close.assert_not_awaited()


class TestGetSizeOfFolder(SimpleTestCase):
    def _mock_s3(self) -> MagicMock:
        s3 = MagicMock()
        s3.find.return_value = {
            "bucket/path/a.parquet": {"Size": 2 * 1024 * 1024, "type": "file"},
            "bucket/path/": {"Size": 0, "type": "directory"},
        }
        s3._s3 = MagicMock()
        return s3

    @patch("products.data_warehouse.backend.s3.s3fs.S3FileSystem.close_session")
    @patch("products.data_warehouse.backend.s3.get_s3_client")
    def test_requests_an_uncached_client_and_computes_size(self, mock_get_s3_client, mock_close_session):
        # This runs from Temporal's sync-activity thread pool. A shared (thread-keyed) client
        # would leak one S3FileSystem per calling thread forever; skip_instance_cache=True is
        # what avoids that.
        mock_get_s3_client.return_value = self._mock_s3()

        total_mib = get_size_of_folder("s3://bucket/path")

        mock_get_s3_client.assert_called_once_with(skip_instance_cache=True)
        assert total_mib == 2.0

    @parameterized.expand([("listing_succeeds", None), ("listing_raises", OSError("[Errno 24] Too many open files"))])
    @patch("products.data_warehouse.backend.s3.s3fs.S3FileSystem.close_session")
    @patch("products.data_warehouse.backend.s3.get_s3_client")
    def test_closes_the_session_regardless_of_outcome(self, _name, error, mock_get_s3_client, mock_close_session):
        s3 = self._mock_s3()
        if error is not None:
            s3.find.side_effect = error
        mock_get_s3_client.return_value = s3

        if error is not None:
            with self.assertRaises(OSError):
                get_size_of_folder("s3://bucket/path")
        else:
            get_size_of_folder("s3://bucket/path")

        mock_close_session.assert_called_once_with(s3.loop, s3._s3creator)
