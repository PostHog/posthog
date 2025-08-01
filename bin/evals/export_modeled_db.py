import os
import subprocess
import tempfile

import boto3
from dagster_pipes import open_dagster_pipes
from pydantic import BaseModel


class ExportConfig(BaseModel):
    class Config:
        extra = "allow"

    database_url: str
    s3_path: str
    file_key: str


def main():
    with (
        open_dagster_pipes() as context,
        tempfile.NamedTemporaryFile(mode="wb", suffix=".tar", delete=False) as temp_file,
    ):
        # Get variables for dumping a DB
        config = ExportConfig.model_validate(context.extras)

        # Build pg_dump command
        pg_dump_cmd = [
            "pg_dump",
            "--format=tar",
            "--compress=9",
            "--verbose",
            "--file",
            temp_file.name,
            config.database_url,
        ]

        context.log.info(f"Dumping database to {temp_file.name}")

        # Execute pg_dump
        subprocess.run(pg_dump_cmd, capture_output=True, text=True, check=True)

        context.log.info(f"Database dump completed: {temp_file.name}")
        context.log.info(f"Dump file size: {os.path.getsize(temp_file.name)} bytes")

        # Upload the dump to S3
        s3_client = boto3.client("s3")
        s3_client.upload_file(temp_file.name, config.s3_path, config.file_key)

        context.log.info(f"Database dump uploaded to {config.s3_path}")
        file_size = os.path.getsize(temp_file.name)
        context.report_asset_materialization(metadata={"size": file_size})
        context.report_asset_check(check_name="no_empty_dump", passed=file_size > 0)


if __name__ == "__main__":
    main()
