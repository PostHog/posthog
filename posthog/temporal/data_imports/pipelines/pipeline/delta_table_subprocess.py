import argparse
import os
from deltalake import DeltaTable


def _get_credentials():
    return {
        "aws_access_key_id": os.getenv("AIRBYTE_BUCKET_KEY", None),
        "aws_secret_access_key": os.getenv("AIRBYTE_BUCKET_SECRET", None),
        "region_name": os.getenv("AIRBYTE_BUCKET_REGION", None),
        "AWS_DEFAULT_REGION": os.getenv("AIRBYTE_BUCKET_REGION", None),
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


def run_operations(table_uri: str) -> None:
    storage_options = _get_credentials()

    delta_table = DeltaTable(table_uri=table_uri, storage_options=storage_options)
    delta_table.optimize.compact()
    delta_table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Delta operations")
    parser.add_argument("--table_uri", required=True, help="S3 table_uri for the delta table")

    args = parser.parse_args()

    run_operations(args.table_uri)
