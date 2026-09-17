import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from botocore.exceptions import ClientError
from parameterized import parameterized

from products.data_warehouse.backend.s3 import aget_s3_client, ensure_bucket_exists, get_size_of_folder


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "operation")


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


class TestEnsureBucketExists(SimpleTestCase):
    @patch("products.data_warehouse.backend.s3.boto3.client")
    def test_does_nothing_when_bucket_already_reachable(self, mock_boto3_client) -> None:
        s3_client = MagicMock()
        mock_boto3_client.return_value = s3_client

        ensure_bucket_exists("s3://my-bucket", "key", "secret")

        s3_client.create_bucket.assert_not_called()

    @patch("products.data_warehouse.backend.s3.boto3.client")
    def test_creates_bucket_when_missing(self, mock_boto3_client) -> None:
        s3_client = MagicMock()
        s3_client.head_bucket.side_effect = _client_error("404")
        mock_boto3_client.return_value = s3_client

        ensure_bucket_exists("s3://my-bucket", "key", "secret")

        s3_client.create_bucket.assert_called_once_with(Bucket="my-bucket")

    @parameterized.expand(
        [
            ("owned_by_us", "BucketAlreadyOwnedByYou", False),
            ("owned_by_someone_else", "BucketAlreadyExists", True),
            ("access_denied", "AccessDenied", True),
        ]
    )
    @patch("products.data_warehouse.backend.s3.boto3.client")
    def test_create_bucket_race_after_a_404(self, _name, create_error_code, should_raise, mock_boto3_client) -> None:
        # A concurrent caller can create the bucket between our head_bucket 404 and our own
        # create_bucket call. BucketAlreadyOwnedByYou means we lost that race but still own the
        # bucket, so it must not surface as a failure; any other create_bucket error is real.
        s3_client = MagicMock()
        s3_client.head_bucket.side_effect = _client_error("404")
        s3_client.create_bucket.side_effect = _client_error(create_error_code)
        mock_boto3_client.return_value = s3_client

        if should_raise:
            with self.assertRaises(ClientError):
                ensure_bucket_exists("s3://my-bucket", "key", "secret")
        else:
            ensure_bucket_exists("s3://my-bucket", "key", "secret")

    @patch("products.data_warehouse.backend.s3.boto3.client")
    def test_skips_check_when_botocore_rejects_the_endpoint(self, mock_boto3_client) -> None:
        # delta-rs accepts endpoints botocore refuses to build a client for (e.g. a service host
        # with an underscore), so a rejected endpoint must not abort the sync at this pre-check.
        mock_boto3_client.side_effect = ValueError("Invalid endpoint: http://object_storage:19000")

        ensure_bucket_exists("s3://my-bucket", "key", "secret", "http://object_storage:19000")

    @patch("products.data_warehouse.backend.s3.boto3.client")
    def test_reraises_unrelated_value_errors(self, mock_boto3_client) -> None:
        mock_boto3_client.side_effect = ValueError("something else went wrong")

        with self.assertRaises(ValueError):
            ensure_bucket_exists("s3://my-bucket", "key", "secret")

    @patch("products.data_warehouse.backend.s3.time.sleep")
    @patch("products.data_warehouse.backend.s3.boto3.client")
    def test_reraises_non_404_head_bucket_errors(self, mock_boto3_client, mock_sleep) -> None:
        s3_client = MagicMock()
        s3_client.head_bucket.side_effect = _client_error("403")
        mock_boto3_client.return_value = s3_client

        with self.assertRaises(ClientError):
            ensure_bucket_exists("s3://my-bucket", "key", "secret")

        # A persistent 403 retries (it's indistinguishable from a transient one, see
        # test_retries_head_bucket_403_then_succeeds) but still gives up and raises.
        assert s3_client.head_bucket.call_count > 1
        s3_client.create_bucket.assert_not_called()

    @patch("products.data_warehouse.backend.s3.time.sleep")
    @patch("products.data_warehouse.backend.s3.boto3.client")
    def test_retries_head_bucket_403_then_succeeds(self, mock_boto3_client, mock_sleep) -> None:
        # HeadBucket carries no body, so a 403 from it can't be told apart from a still-registering
        # local object store (e.g. SeaweedFS's credential bootstrap loop) by message alone. That
        # transient race must self-heal on retry instead of surfacing as a hard failure.
        s3_client = MagicMock()
        s3_client.head_bucket.side_effect = [_client_error("403"), _client_error("403"), None]
        mock_boto3_client.return_value = s3_client

        ensure_bucket_exists("s3://my-bucket", "key", "secret")

        assert s3_client.head_bucket.call_count == 3
        s3_client.create_bucket.assert_not_called()
