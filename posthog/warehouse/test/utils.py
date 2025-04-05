import s3fs
import pyarrow as pa
import pandas as pd
import pyarrow.parquet as pq
from typing import Optional

from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.models.team import Team


from posthog.settings import (
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    OBJECT_STORAGE_ENDPOINT,
    XDIST_SUFFIX,
)


def create_data_warehouse_table_from_csv(
    csv_path: str,
    table_name: str,
    table_columns: dict[str, str],
    test_bucket: str,
    team: Team,
    *,
    source: Optional[ExternalDataSource] = None,
    credential: Optional[DataWarehouseCredential] = None,
    source_prefix: Optional[str] = None,
):
    # Initialize S3 filesystem
    if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
        raise Exception("Missing S3 credentials")

    fs = s3fs.S3FileSystem(
        client_kwargs={
            "region_name": "us-east-1",
            "endpoint_url": OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
        },
    )

    # Read CSV and convert to parquet
    df = pd.read_csv(csv_path)
    csv_data = pa.Table.from_pandas(df)

    # Append XDIST_SUFFIX to test bucket if it exists
    test_bucket = test_bucket + XDIST_SUFFIX

    path_to_s3_object = "s3://" + OBJECT_STORAGE_BUCKET + f"/{test_bucket}"
    pq.write_to_dataset(
        csv_data,
        path_to_s3_object,
        filesystem=fs,
        use_dictionary=True,
        compression="snappy",
    )

    if source is None:
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSource.Type.STRIPE,
            prefix=source_prefix or "posthog_test_",
        )

    if credential is None:
        credential = DataWarehouseCredential.objects.create(
            team=team,
            access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
            access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        )

    table = DataWarehouseTable.objects.create(
        name=table_name,
        format=DataWarehouseTable.TableFormat.Parquet,
        team=team,
        credential=credential,
        url_pattern=f"http://host.docker.internal:19000/{OBJECT_STORAGE_BUCKET}/{test_bucket}/*.parquet",
        columns=table_columns,
    )

    # This should, in theory, be called in the test tear down
    # to get rid of the test data from S3
    def cleanUp():
        try:
            fs.rm(f"{OBJECT_STORAGE_BUCKET}/{test_bucket}", recursive=True)
        except:
            pass

    return (table, source, credential, csv_data, cleanUp)
