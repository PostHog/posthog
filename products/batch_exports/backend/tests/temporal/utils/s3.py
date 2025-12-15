import gzip
import json
import datetime as dt
import functools

from django.conf import settings

import brotli
import aioboto3
import pyarrow.parquet as pq
from pyarrow import fs
from types_aiobotocore_s3.client import S3Client

from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
)

SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


async def read_parquet_from_s3(
    s3_client: S3Client,
    bucket_name: str,
    key: str,
    json_columns,
) -> list:
    credentials = s3_client._request_signer._credentials  # type: ignore
    endpoint_url = s3_client.meta.endpoint_url

    s3 = fs.S3FileSystem(
        access_key=credentials.access_key,
        secret_key=credentials.secret_key,
        endpoint_override=endpoint_url,
    )

    table = pq.read_table(f"{bucket_name}/{key}", filesystem=s3)

    parquet_data = []
    for batch in table.to_batches():
        for record in batch.to_pylist():
            casted_record = {}
            for k, v in record.items():
                if isinstance(v, dt.datetime):
                    # We read data from clickhouse as string, but parquet already casts them as dates.
                    # To facilitate comparison, we isoformat the dates.
                    casted_record[k] = v.isoformat()
                elif k in json_columns and v is not None:
                    # Parquet doesn't have a variable map type, so JSON fields are just strings.
                    casted_record[k] = json.loads(v)
                else:
                    casted_record[k] = v
            parquet_data.append(casted_record)

    return parquet_data


def read_s3_data_as_json(data: bytes, compression: str | None) -> list:
    match compression:
        case "gzip":
            data = gzip.decompress(data)
        case "brotli":
            data = brotli.decompress(data)
        case _:
            pass

    json_data = [json.loads(line) for line in data.decode("utf-8").split("\n") if line]
    return json_data


async def delete_all_from_s3(s3_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = await s3_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                await s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])


async def assert_files_in_s3(s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns):
    """Assert that there are files in S3 under key_prefix and return the combined contents, and the keys of files found."""
    if file_format == "Arrow":
        expected_file_extension = "arrow"
    else:
        expected_file_extension = FILE_FORMAT_EXTENSIONS[file_format]
    if compression is not None:
        expected_file_extension = f"{expected_file_extension}.{COMPRESSION_EXTENSIONS[compression]}"

    objects = await s3_compatible_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    s3_data = []
    keys = []
    assert objects.get("KeyCount", 0) > 0
    assert "Contents" in objects
    for obj in objects["Contents"]:
        key = obj.get("Key")
        if not key.endswith(expected_file_extension):
            continue

        keys.append(key)

        if file_format == "Parquet":
            s3_data.extend(
                await read_parquet_from_s3(
                    s3_client=s3_compatible_client,
                    bucket_name=bucket_name,
                    key=key,
                    json_columns=json_columns,
                )
            )

        elif file_format == "Arrow":
            s3_object = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
            data = await s3_object["Body"].read()
            s3_data.extend(data)
        elif file_format == "JSONLines":
            s3_object = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
            data = await s3_object["Body"].read()
            s3_data.extend(read_s3_data_as_json(data, compression))
        else:
            raise ValueError(f"Unsupported file format: {file_format}")

    return s3_data, keys


async def assert_file_in_s3(s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns):
    """Assert a file is in S3 and return its contents."""
    s3_data, keys = await assert_files_in_s3(
        s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns
    )
    assert len(keys) == 1
    return s3_data


async def assert_no_files_in_s3(s3_compatible_client, bucket_name, key_prefix):
    """Assert that there are no files in S3 under key_prefix."""
    objects = await s3_compatible_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)
    assert len(objects.get("Contents", [])) == 0


async def read_json_file_from_s3(s3_compatible_client, bucket_name, key) -> list | dict:
    s3_object: dict = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
    data = await s3_object["Body"].read()
    data = read_s3_data_as_json(data, None)
    return data[0]
