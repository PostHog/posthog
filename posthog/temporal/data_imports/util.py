import re
import asyncio
from datetime import datetime
from typing import Literal, Optional

from django.conf import settings

from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger

from posthog.exceptions import capture_exception
from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool

from products.data_warehouse.backend.s3 import aget_s3_client


class NonRetryableException(Exception):
    @property
    def cause(self) -> Optional[BaseException]:
        """Cause of the exception.

        This is the same as ``Exception.__cause__``.
        """
        return self.__cause__


# 10 mins buffer to avoid deleting files Clickhouse may be reading
S3_DELETE_TIME_BUFFER = 600


def is_posthog_team(team_id: int) -> bool:
    DEBUG: bool = get_from_env("DEBUG", False, type_cast=str_to_bool)
    if DEBUG:
        return True

    region = get_from_env("CLOUD_DEPLOYMENT", optional=True)
    return (region == "EU" and team_id == 1) or (region == "US" and team_id == 2)


async def prepare_s3_files_for_querying(
    folder_path: str,
    table_name: str,
    file_uris: list[str],
    use_timestamped_folders: bool = True,
    existing_queryable_folder: Optional[str] = None,
    preserve_table_name_casing: Optional[bool] = False,
    delete_existing: bool = True,
    logger: Optional[FilteringBoundLogger] = None,
) -> str:
    """Async version that uses s3fs native async methods for concurrent file operations."""

    async def _log(msg: str, level: Optional[Literal["debug", "error"]] = "debug") -> None:
        if logger:
            if level == "debug":
                await logger.adebug(msg)
            elif level == "error":
                await logger.aerror(msg)

    await _log(
        f"Preparing S3 files for querying for table {table_name} in folder {folder_path}. "
        f"delete_existing={delete_existing}. use_timestamped_folders={use_timestamped_folders}."
    )

    async with aget_s3_client() as s3:
        s3.invalidate_cache()

        normalized_table_name = NamingConvention().normalize_identifier(table_name)

        s3_folder_for_job = f"{settings.BUCKET_URL}/{folder_path}"

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

        files_to_delete: list[str] = []
        if delete_existing:
            if use_timestamped_folders:
                query_folder_pattern = re.compile(r"^.+?\_\_query\_(\d+)\/?$")

                all_files = await s3._ls(s3_folder_for_job, detail=True)
                all_file_values = all_files.values() if isinstance(all_files, dict) else all_files
                directories = [f["Key"] for f in all_file_values if f["type"] == "directory"]

                await _log(f"Found existing directories: {directories}")

                timestamped_query_folders: list[tuple[str, int]] = []
                for directory in directories:
                    match = query_folder_pattern.match(directory)
                    if match:
                        timestamped_query_folders.append((directory, int(match.group(1))))

                timestamped_query_folders.sort(key=lambda x: x[1])
                total_dirs = len(timestamped_query_folders)

                for index, directory in enumerate(timestamped_query_folders):
                    directory_path, directory_timestamp = directory
                    if existing_queryable_folder:
                        if existing_queryable_folder == f"{normalized_table_name}__query_{directory_timestamp}":
                            await _log(f"Skipping deletion of existing querying folder: {directory_path}")
                            continue
                    else:
                        if index == total_dirs - 1:
                            await _log(f"Skipping deletion of most recent query folder: {directory_path}")
                            continue

                    try:
                        if (datetime.now().timestamp() - directory_timestamp) >= S3_DELETE_TIME_BUFFER:
                            files_to_delete.append(directory_path)

                        old_query_folder = f"{s3_folder_for_job}/{normalized_table_name}__query"
                        if await s3._exists(old_query_folder):
                            files_to_delete.append(old_query_folder)
                    except Exception as e:
                        await _log(f"Error while checking old query folders: {e}", level="error")
                        capture_exception(e)
            else:
                if await s3._exists(s3_path_for_querying):
                    files_to_delete.append(s3_path_for_querying)

        # Copy files concurrently with limited concurrency to avoid overwhelming S3
        await _log(f"Copying {len(file_uris)} files to {s3_path_for_querying}")

        semaphore = asyncio.Semaphore(50)

        async def copy_file(file: str) -> None:
            async with semaphore:
                file_name = file.replace(f"{s3_folder_for_schema}/", "")
                await s3._copy(file, f"{s3_path_for_querying}/{file_name}")

        await asyncio.gather(*[copy_file(file) for file in file_uris])

        # Delete existing files after copying new ones
        if delete_existing and files_to_delete:
            await _log(f"Deleting {len(files_to_delete)} old query folders")

            async def delete_folder(file: str) -> None:
                async with semaphore:
                    try:
                        await s3._rm(file, recursive=True)
                    except Exception as e:
                        await _log(f"Error while deleting old query folder {file}: {e}", level="error")
                        capture_exception(e)

            await asyncio.gather(*[delete_folder(file) for file in files_to_delete])

        await _log(f"Returning S3 folder for querying: {s3_folder_for_querying}")

    return s3_folder_for_querying
