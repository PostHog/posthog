from typing import Optional

from django.conf import settings

from dlt.common.normalizers.naming.snake_case import NamingConvention

from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool
from posthog.warehouse.s3 import get_s3_client


def prepare_s3_files_for_querying(
    folder_path: str,
    table_name: str,
    file_uris: list[str],
    preserve_table_name_casing: Optional[bool] = False,
    delete_existing: bool = True,
):
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

    s3_folder_for_querying = f"{s3_folder_for_job}/{normalized_table_name}__query"

    # TODO - maybe we should move these to a separate place and then delete them after the copy is done, to avoid any
    # downtime?
    if delete_existing:
        if s3.exists(s3_folder_for_querying):
            s3.delete(s3_folder_for_querying, recursive=True)

    for file in file_uris:
        file_name = file.replace(f"{s3_folder_for_schema}/", "")
        s3.copy(file, f"{s3_folder_for_querying}/{file_name}")


def is_posthog_team(team_id: int) -> bool:
    DEBUG: bool = get_from_env("DEBUG", False, type_cast=str_to_bool)
    if DEBUG:
        return True

    region = get_from_env("CLOUD_DEPLOYMENT", optional=True)
    return (region == "EU" and team_id == 1) or (region == "US" and team_id == 2)
