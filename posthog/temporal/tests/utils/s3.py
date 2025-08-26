import os
import gzip
import json
import datetime as dt

from django.conf import settings

import brotli
import aioboto3
import botocore
import pyarrow.parquet as pq
from pyarrow import fs


async def read_parquet_from_s3(
    bucket_name: str,
    key: str,
    json_columns,
    access_key="object_storage_root_user",
    secret_key="object_storage_root_password",
) -> list:
    async with aioboto3.Session().client("sts") as sts:
        try:
            await sts.get_caller_identity()
        except botocore.exceptions.ClientError:
            s3 = fs.S3FileSystem(
                access_key=access_key,
                secret_key=secret_key,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )
        except botocore.exceptions.NoCredentialsError:
            s3 = fs.S3FileSystem(
                access_key=access_key,
                secret_key=secret_key,
                endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
            )

        else:
            if os.getenv("S3_TEST_BUCKET") is not None:
                s3 = fs.S3FileSystem()
            else:
                s3 = fs.S3FileSystem(
                    access_key=access_key,
                    secret_key=secret_key,
                    endpoint_override=settings.OBJECT_STORAGE_ENDPOINT,
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
