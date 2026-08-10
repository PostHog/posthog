import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from products.data_warehouse.backend.s3 import aget_s3_client


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
