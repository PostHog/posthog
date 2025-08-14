import os
import subprocess
import tempfile

import boto3
from dagster_pipes import open_dagster_pipes

from dags.max_ai.shared import EvalsDockerImageConfig


def main():
    with (
        open_dagster_pipes() as context,
        tempfile.NamedTemporaryFile(mode="wb", suffix=".tar", delete=False) as temp_file,
    ):
        # Get variables for dumping a DB
        config = EvalsDockerImageConfig.model_validate(context.extras)

        # Build pg_dump command
        pg_dump_cmd = [
            "pg_dump",
            "--format=custom",
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
        s3_client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_ACCESS_KEY"),
        )
        s3_client.upload_file(temp_file.name, config.bucket_name, config.file_key)

        context.log.info(f"Database dump uploaded to {config.bucket_name}/{config.file_key}")
        file_size = os.path.getsize(temp_file.name)
        context.report_asset_materialization(metadata={"size": file_size})
        context.report_asset_check(check_name="no_empty_dump", passed=file_size > 0)


if __name__ == "__main__":
    main()
