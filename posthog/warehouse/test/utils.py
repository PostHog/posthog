from collections.abc import Mapping
from pathlib import Path
from typing import Optional

import s3fs
import pandas as pd

from posthog.models.team import Team
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
    XDIST_SUFFIX,
)
from posthog.warehouse.models import CLICKHOUSE_HOGQL_MAPPING, clean_type
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.types import ExternalDataSourceType


def create_data_warehouse_table_from_csv(
    csv_path: Path,
    table_name: str,
    table_columns: Mapping[str, str | Mapping[str, str | bool]],
    test_bucket: str,
    team: Team,
    *,
    source: Optional[ExternalDataSource] = None,
    credential: Optional[DataWarehouseCredential] = None,
    source_prefix: Optional[str] = None,
):
    if not csv_path.exists():
        raise FileNotFoundError(f"Test data file not found at {csv_path}")

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

    # Read CSV
    df = pd.read_csv(csv_path)

    # Append XDIST_SUFFIX to test bucket if it exists
    test_bucket = test_bucket + XDIST_SUFFIX

    # Guarantee prefix is valid
    if source_prefix is None:
        source_prefix = "posthog_test_"
    table_name = f"{source_prefix}{table_name}"

    # Write CSV directly to S3
    folder = f"{OBJECT_STORAGE_BUCKET}/{test_bucket}/{table_name}"
    path_to_s3_object = f"{folder}/data.csv"
    with fs.open(path_to_s3_object, "wb", blocksize=None) as f:
        df.to_csv(f, index=False)

    if source is None:
        source = ExternalDataSource.objects.create(
            team=team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            prefix=source_prefix,
        )

    if credential is None:
        credential = DataWarehouseCredential.objects.create(
            team=team,
            access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
            access_secret=OBJECT_STORAGE_SECRET_ACCESS_KEY,
        )

    if any(isinstance(value, str) for value in table_columns.values()):
        table_columns = {
            str(key): {
                "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(str(value))].__name__,
                "clickhouse": value,
                "valid": True,
            }
            for key, value in table_columns.items()
        }

    table = DataWarehouseTable.objects.create(
        name=table_name,
        format=DataWarehouseTable.TableFormat.CSVWithNames,
        team=team,
        external_data_source=source,
        credential=credential,
        url_pattern=f"http://host.docker.internal:19000/{folder}/*.csv",
        columns=table_columns,
    )

    # This should, in theory, be called in the test tear down
    # to get rid of the test data from S3
    def cleanUp():
        try:
            fs.rm(folder, recursive=True)
        except:
            pass

    return (table, source, credential, df, cleanUp)
