"""Locations in S3 that the ClickHouse cluster reads and writes through its ``s3(...)`` table function."""

from django.conf import settings

from posthog.dataclasses import frozen


@frozen
class S3StagingLocation:
    """A bucket and key prefix that the ClickHouse cluster reaches through ``s3(...)``.

    ``endpoint`` is set for local, dev and test object storage, and it must be an endpoint the
    cluster can reach, which is not always the one the Python process uses. On prod it is empty and
    the cluster reaches the bucket through its attached IAM role.
    """

    bucket: str
    prefix: str
    region: str
    endpoint: str | None

    @classmethod
    def for_dictionaries(cls) -> "S3StagingLocation":
        return cls(
            bucket=settings.DICTIONARY_STAGING_S3_BUCKET,
            prefix=settings.DICTIONARY_STAGING_S3_PREFIX,
            region=settings.DICTIONARY_STAGING_S3_REGION,
            endpoint=settings.DICTIONARY_STAGING_S3_ENDPOINT,
        )

    @classmethod
    def for_data_deletion(cls) -> "S3StagingLocation":
        return cls(
            bucket=settings.DATA_DELETION_STAGING_S3_BUCKET,
            prefix=settings.DATA_DELETION_STAGING_S3_PREFIX,
            region=settings.DATA_DELETION_STAGING_S3_REGION,
            endpoint=settings.DATA_DELETION_STAGING_S3_ENDPOINT,
        )

    def object_key(self, key: str) -> str:
        """The full object key under this location's prefix, for a boto3 client."""
        return f"{self.prefix}/{key}"

    def s3_args(self, key: str, file_format: str, structure: str | None = None) -> str:
        """The argument list for a ClickHouse ``s3(...)`` call over ``key``.

        ``key`` may contain ClickHouse glob or ``{_partition_id}`` placeholders. Credentials are
        emitted only where an endpoint is configured, so no secret is ever interpolated into SQL
        on prod.
        """
        path = self.object_key(key)
        if self.endpoint:
            url = f"{self.endpoint}/{self.bucket}/{path}"
            creds = f"'{settings.OBJECT_STORAGE_ACCESS_KEY_ID}', '{settings.OBJECT_STORAGE_SECRET_ACCESS_KEY}', "
        else:
            url = f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{path}"
            creds = ""
        args = f"'{url}', {creds}'{file_format}'"
        if structure is None:
            return args
        # The structure sits inside a single-quoted SQL literal, so escape the quotes in a type like
        # DateTime64(6, 'UTC') or they terminate the literal early.
        escaped = " ".join(structure.split()).replace("'", "\\'")
        return f"{args}, '{escaped}'"
