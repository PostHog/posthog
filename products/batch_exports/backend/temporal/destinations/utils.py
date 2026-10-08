import datetime as dt
import posixpath

from posthog.temporal.common.logger import get_logger

from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.destinations.constants import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
)
from products.batch_exports.backend.temporal.errors import MissingRequiredInputsError

EXTERNAL_LOGGER = get_logger("EXTERNAL")


def get_allowed_template_variables(
    data_interval_start: str | None, data_interval_end: str, batch_export_model: BatchExportModel | None
) -> dict[str, str]:
    """Derive from inputs a dictionary of supported template variables for key prefixes."""
    export_datetime = dt.datetime.fromisoformat(data_interval_end)

    return {
        "second": f"{export_datetime:%S}",
        "minute": f"{export_datetime:%M}",
        "hour": f"{export_datetime:%H}",
        "day": f"{export_datetime:%d}",
        "month": f"{export_datetime:%m}",
        "year": f"{export_datetime:%Y}",
        "data_interval_start": data_interval_start or "START",
        "data_interval_end": data_interval_end,
        "table": batch_export_model.name if batch_export_model is not None else "events",
    }


def get_key_prefix(
    prefix: str, data_interval_start: str | None, data_interval_end: str, batch_export_model: BatchExportModel | None
) -> str:
    """Format a key prefix with template variables."""
    template_variables = get_allowed_template_variables(data_interval_start, data_interval_end, batch_export_model)

    try:
        return prefix.format(**template_variables)
    except (KeyError, ValueError) as e:
        EXTERNAL_LOGGER.warning(
            f"The key prefix '{prefix}' will be used as-is since it contains invalid template variables: {str(e)}"
        )
        return prefix


def get_absolute_key_prefix(
    prefix: str, data_interval_start: str | None, data_interval_end: str, batch_export_model: BatchExportModel | None
) -> str:
    """Like `get_key_prefix`, but ensure key is absolute and ends on a slash."""
    key_prefix = get_key_prefix(prefix, data_interval_start, data_interval_end, batch_export_model)

    # Empty string becomes "/", prefixes without a leading "/" get one,
    # and for everything else this is a no-op.
    key_prefix = posixpath.join("/", key_prefix)
    # Ensures a trailing slash, as all of our object keys join on the prefix,
    # which means they end up after a slash.
    key_prefix = posixpath.join(key_prefix, "")
    return key_prefix


def get_manifest_key(
    prefix: str,
    data_interval_start: str | None,
    data_interval_end: str | None,
    batch_export_model: BatchExportModel | None,
    file_name_prefix: str | None = None,
) -> str:
    """Generate manifest file key."""
    if file_name_prefix is not None and (data_interval_start is None or data_interval_end is None):
        return posixpath.join(prefix, f"{file_name_prefix}_manifest.json")
    if data_interval_end is None:
        raise MissingRequiredInputsError("Provide a filename prefix for an export without an end bound.")
    key_prefix = get_key_prefix(prefix, data_interval_start, data_interval_end, batch_export_model)
    return posixpath.join(key_prefix, f"{data_interval_start}-{data_interval_end}_manifest.json")


def _get_compression_extension(file_format: str, compression: str | None, legacy_parquet_extension: bool) -> str | None:
    """Resolve the codec suffix that follows the file format extension, if any.

    Parquet gets no codec suffix, because it records the codec inside the file and a reader opens
    it as Parquet whatever the codec is. `legacy_parquet_extension` keeps the suffix for an export
    that already wrote Parquet files before this rule, whose downstream pipeline may match on the
    old names.
    """
    if compression is None:
        return None

    if file_format == "Parquet" and not legacy_parquet_extension:
        return None

    return COMPRESSION_EXTENSIONS[compression]


def get_object_key(
    prefix: str,
    data_interval_start: str | None,
    data_interval_end: str | None,
    batch_export_model: BatchExportModel | None,
    file_format: str,
    compression: str | None = None,
    legacy_parquet_extension: bool = False,
    file_number: int = 0,
    include_file_number: bool = False,
    file_name_prefix: str | None = None,
) -> str:
    """Generate object storage key for batch export files."""
    if file_name_prefix is not None and (data_interval_start is None or data_interval_end is None):
        key_prefix = prefix
        base_file_name = file_name_prefix
        include_file_number = True
    else:
        if data_interval_end is None:
            raise MissingRequiredInputsError("Provide a filename prefix for an export without an end bound.")
        key_prefix = get_key_prefix(prefix, data_interval_start, data_interval_end, batch_export_model)
        base_file_name = f"{data_interval_start}-{data_interval_end}"

    if include_file_number:
        base_file_name = f"{base_file_name}-{file_number}"

    file_extension = FILE_FORMAT_EXTENSIONS[file_format]
    compression_extension = _get_compression_extension(file_format, compression, legacy_parquet_extension)

    if compression_extension is not None:
        file_name = f"{base_file_name}.{file_extension}.{compression_extension}"
    else:
        file_name = f"{base_file_name}.{file_extension}"

    key = posixpath.join(key_prefix, file_name)

    if posixpath.isabs(key):
        key = posixpath.relpath(key, "/")

    return key


def get_query_timeout(data_interval_start: dt.datetime | None, data_interval_end: dt.datetime) -> float:
    """Get the timeout to use for long running queries.

    Operations like COPY INTO TABLE and MERGE can take a long time to complete, especially if there is a lot of data and
    the instance being used is not very powerful. We don't want to allow these queries to run for too long, as they can
    cause SLA violations and can consume a lot of resources in the user's instance.
    """
    min_timeout_seconds = 20 * 60  # 20 minutes
    max_timeout_seconds = 6 * 60 * 60  # 6 hours

    if data_interval_start is None:
        return max_timeout_seconds

    interval_seconds = (data_interval_end - data_interval_start).total_seconds()
    # We don't want the timeout to be too short (eg in case of 5 min batch exports)
    timeout_seconds = max(min_timeout_seconds, interval_seconds * 0.8)
    # We don't want the timeout to be too long (eg in case of 1 day batch exports)
    return min(timeout_seconds, max_timeout_seconds)
