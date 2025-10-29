import re
from datetime import datetime
from typing import Literal, Optional

from django.conf import settings

from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger

from posthog.settings.utils import get_from_env
from posthog.temporal.data_imports.deltalake_compaction_job import capture_exception
from posthog.utils import str_to_bool
from posthog.warehouse.s3 import get_s3_client

# 10 mins buffer to avoid deleting files Clickhouse may be reading
S3_DELETE_TIME_BUFFER = 600


def prepare_s3_files_for_querying(
    folder_path: str,
    table_name: str,
    file_uris: list[str],
    use_timestamped_folders: bool = True,
    existing_queryable_folder: Optional[str] = None,
    preserve_table_name_casing: Optional[bool] = False,
    delete_existing: bool = True,
    logger: Optional[FilteringBoundLogger] = None,
) -> str:
    """Copies files from a given S3 folder to a new S3 folder that is used for querying.
    This is done to ensure that the files are in a consistent state before querying.

    Returns the folder that can be used for querying. Note: this isn't the whole S3 path, just the last directory, e.g. table__query
    """

    def _log(msg: str, level: Optional[Literal["debug", "error"]] = "debug") -> None:
        if logger:
            if level == "debug":
                logger.debug(msg)
            elif level == "error":
                logger.error(msg)

    _log(
        f"Preparing S3 files for querying for table {table_name} in folder {folder_path}. delete_existing={delete_existing}. use_timestamped_folders={use_timestamped_folders}."
    )

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
        files_to_delete: list[str] = []
        if use_timestamped_folders:
            query_folder_pattern = re.compile(r"^.+?\_\_query\_(\d+)\/?$")

            all_files = s3.ls(s3_folder_for_job, detail=True)
            all_file_values = all_files.values() if isinstance(all_files, dict) else all_files
            directories = [f["Key"] for f in all_file_values if f["type"] == "directory"]

            _log(f"Found existing directories: {directories}")

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
                if existing_queryable_folder:
                    if existing_queryable_folder == f"{normalized_table_name}__query_{directory_timestamp}":
                        _log(f"Skipping deletion of existing querying folder: {directory_path}")
                        continue
                else:
                    if index == total_dirs - 1:
                        _log(f"Skipping deletion of most recent query folder: {directory_path}")
                        continue

                try:
                    if (datetime.now().timestamp() - directory_timestamp) >= S3_DELETE_TIME_BUFFER:
                        files_to_delete.append(directory_path)

                    # Delete the old format query folder if it exists
                    old_query_folder = f"{s3_folder_for_job}/{normalized_table_name}__query"
                    if s3.exists(old_query_folder):
                        files_to_delete.append(old_query_folder)
                except Exception as e:
                    _log(f"Error while checking old query folders: {e}", level="error")
                    capture_exception(e)
        else:
            if s3.exists(s3_path_for_querying):
                files_to_delete.append(s3_path_for_querying)

    for file in file_uris:
        file_name = file.replace(f"{s3_folder_for_schema}/", "")
        _log(f"Copying file {file} to {s3_path_for_querying}/{file_name}")
        s3.copy(file, f"{s3_path_for_querying}/{file_name}")

    # Delete existing files after copying new ones. In the event of a pod OOM during file
    # copying, the queryable_folder can get out of date and attempt to query deleted files.
    if delete_existing and files_to_delete:
        for file in files_to_delete:
            _log(f"Deleting existing querying folder {file}")
            try:
                s3.delete(file, recursive=True)
            except Exception as e:
                _log(f"Error while deleting old query folder {file}: {e}", level="error")
                capture_exception(e)

    _log(f"Returning S3 folder for querying: {s3_folder_for_querying}")

    return s3_folder_for_querying


def is_posthog_team(team_id: int) -> bool:
    DEBUG: bool = get_from_env("DEBUG", False, type_cast=str_to_bool)
    if DEBUG:
        return True

    region = get_from_env("CLOUD_DEPLOYMENT", optional=True)
    return (region == "EU" and team_id == 1) or (region == "US" and team_id == 2)
