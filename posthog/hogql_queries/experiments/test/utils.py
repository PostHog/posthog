from posthog.models.team.team import Team
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)
import s3fs
from pyarrow import parquet as pq
import pyarrow as pa
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.table import DataWarehouseTable

TEST_BUCKET = "test_storage_bucket-posthog.hogql.experiments.queryrunner" + XDIST_SUFFIX


def create_data_warehouse_table(team: Team, table_name: str, table_data: list[dict], columns: dict[str, str]):
    if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
        raise Exception("Missing vars")

    fs = s3fs.S3FileSystem(
        client_kwargs={
            "region_name": "us-east-1",
            "endpoint_url": OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
        },
    )

    path_to_s3_object = "s3://" + OBJECT_STORAGE_BUCKET + f"/{TEST_BUCKET}"

    pq.write_to_dataset(
        pa.Table.from_pylist(table_data),
        path_to_s3_object,
        filesystem=fs,
        use_dictionary=True,
        compression="snappy",
    )

    credential = DataWarehouseCredential.objects.create(
        access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
        access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        team=team,
    )

    DataWarehouseTable.objects.create(
        name=table_name,
        url_pattern=f"http://host.docker.internal:19000/{OBJECT_STORAGE_BUCKET}/{TEST_BUCKET}/*.parquet",
        format=DataWarehouseTable.TableFormat.Parquet,
        team=team,
        columns=columns,
        credential=credential,
    )
    return table_name
