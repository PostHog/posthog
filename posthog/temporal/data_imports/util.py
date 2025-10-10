import re
from datetime import datetime
from typing import Optional

from django.conf import settings

from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.settings.utils import get_from_env
from posthog.temporal.data_imports.deltalake_compaction_job import capture_exception
from posthog.utils import str_to_bool
from posthog.warehouse.s3 import get_s3_client

S3_DELETE_TIME_BUFFER = 600


def prepare_s3_files_for_querying(
    folder_path: str,
    table_name: str,
    file_uris: list[str],
    preserve_table_name_casing: Optional[bool] = False,
    delete_existing: bool = True,
    use_timestamped_folders: bool = False,
) -> str:
    """Copies files from a given S3 folder to a new S3 folder that is used for querying.
    This is done to ensure that the files are in a consistent state before querying.

    Returns the folder that can be used for querying. Note: this isn't the whole S3 path, just the last directory, e.g. table__query
    """

    s3 = get_s3_client()
    s3.invalidate_cache()

    normalized_table_name = NamingConvention().normalize_identifier(table_name)

    s3_folder_for_job = f"{settings.BUCKET_URL}/{folder_path}"

    # Dont use the normalized table name when renaming files when called from the data modeling job
    s3_folder_for_schema = (
        f"{s3_folder_for_job}/{table_name}"
        if preserve_table_name_casing is True
        else f"{s3_folder_for_job}/{normalized_table_name}"
    )

    s3_folder_for_querying = f"{normalized_table_name}__query"
    s3_path_for_querying = f"{s3_folder_for_job}/{s3_folder_for_querying}"
    if use_timestamped_folders:
        timestamp = int(datetime.now().timestamp())
        s3_path_for_querying = f"{s3_path_for_querying}_{timestamp}"
        s3_folder_for_querying = f"{s3_folder_for_querying}_{timestamp}"

    if delete_existing:
        if use_timestamped_folders:
            query_folder_pattern = re.compile(r"^.+?\_\_query\_(\d+)\/?$")

            all_files = s3.ls(s3_folder_for_job, detail=True)
            all_file_values = all_files.values() if isinstance(all_files, dict) else all_files
            directories = [f["Key"] for f in all_file_values if f["type"] == "directory"]

            timestamped_query_folders: list[tuple[str, int]] = []
            for directory in directories:
                match = query_folder_pattern.match(directory)
                if match:
                    timestamped_query_folders.append((directory, int(match.group(1))))

            # Sort by timestamp ascending
            timestamped_query_folders.sort(key=lambda x: x[1])
            total_dirs = len(timestamped_query_folders)

            # Delete query folders if it's older than 10 minutes except for the last folder
            for index, directory in enumerate(timestamped_query_folders):
                directory_path, directory_timestamp = directory
                if index == total_dirs - 1:
                    continue

                try:
                    if (datetime.now().timestamp() - directory_timestamp) >= S3_DELETE_TIME_BUFFER:  # 10 mins
                        s3.delete(directory_path, recursive=True)

                    # Delete the old format query folder if it exists
                    old_query_folder = f"{s3_folder_for_job}/{normalized_table_name}__query"
                    if s3.exists(old_query_folder):
                        s3.delete(old_query_folder, recursive=True)
                except Exception as e:
                    capture_exception(e)
        else:
            if s3.exists(s3_path_for_querying):
                s3.delete(s3_path_for_querying, recursive=True)

    for file in file_uris:
        file_name = file.replace(f"{s3_folder_for_schema}/", "")
        s3.copy(file, f"{s3_path_for_querying}/{file_name}")

    return s3_folder_for_querying


def is_posthog_team(team_id: int) -> bool:
    DEBUG: bool = get_from_env("DEBUG", False, type_cast=str_to_bool)
    if DEBUG:
        return True

    region = get_from_env("CLOUD_DEPLOYMENT", optional=True)
    return (region == "EU" and team_id == 1) or (region == "US" and team_id == 2)
