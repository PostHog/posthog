from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.dags.common.s3_staging import S3StagingLocation


@override_settings(OBJECT_STORAGE_ACCESS_KEY_ID="test-key-id", OBJECT_STORAGE_SECRET_ACCESS_KEY="test-secret")
class TestS3StagingLocation(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "prod reaches the bucket through the node role, with no keys in SQL",
                None,
                None,
                "'https://bucket.s3.us-east-1.amazonaws.com/staging/a/{_partition_id}.native', 'Native'",
            ),
            (
                "local object storage gets path-style URLs and keys",
                "http://objectstorage:19000",
                None,
                "'http://objectstorage:19000/bucket/staging/a/{_partition_id}.native', "
                "'test-key-id', 'test-secret', 'Native'",
            ),
            (
                "a structure with quoted types stays one SQL literal",
                None,
                "ts DateTime64(6, 'UTC'),\n  id UUID",
                "'https://bucket.s3.us-east-1.amazonaws.com/staging/a/{_partition_id}.native', 'Native', "
                "'ts DateTime64(6, \\'UTC\\'), id UUID'",
            ),
        ]
    )
    def test_s3_args(self, _name: str, endpoint: str | None, structure: str | None, expected: str) -> None:
        location = S3StagingLocation(bucket="bucket", prefix="staging", region="us-east-1", endpoint=endpoint)

        args = location.s3_args("a/{_partition_id}.native", "Native", structure)

        self.assertEqual(args, expected)
        if endpoint is None:
            self.assertNotIn("test-secret", args)
