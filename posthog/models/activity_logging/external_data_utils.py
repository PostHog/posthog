from typing import Optional


def get_external_data_source_detail_name(external_data_source) -> str:
    """Generate detail name for ExternalDataSource activity"""
    source_type = external_data_source.source_type or "unknown"

    if external_data_source.prefix:
        return f"{source_type} ({external_data_source.prefix})"

    return source_type


def get_external_data_schema_detail_name(external_data_schema) -> str:
    """Generate detail name for ExternalDataSchema activity"""
    name = external_data_schema.name or "Unnamed Schema"
    sync_type = external_data_schema.sync_type or "unknown"

    # Use the deprecated sync_frequency if available, otherwise use sync_frequency_interval
    sync_frequency = None
    if hasattr(external_data_schema, "sync_frequency") and external_data_schema.sync_frequency:
        sync_frequency = external_data_schema.sync_frequency
    elif external_data_schema.sync_frequency_interval:
        # Convert timedelta to human-readable format
        days = external_data_schema.sync_frequency_interval.days
        hours = external_data_schema.sync_frequency_interval.seconds // 3600

        if days > 0:
            if days == 1:
                sync_frequency = "daily"
            elif days == 7:
                sync_frequency = "weekly"
            elif days >= 30:
                sync_frequency = "monthly"
            else:
                sync_frequency = f"{days}d"
        elif hours > 0:
            if hours == 1:
                sync_frequency = "hourly"
            elif hours == 6:
                sync_frequency = "6h"
            elif hours == 12:
                sync_frequency = "12h"
            else:
                sync_frequency = f"{hours}h"

    if sync_frequency:
        return f"{name} ({sync_type}, {sync_frequency})"

    return f"{name} ({sync_type})"


def get_external_data_source_created_by_info(
    external_data_source,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Get created by user information from ExternalDataSource"""
    created_by_user_id = None
    created_by_user_email = None
    created_by_user_name = None

    if hasattr(external_data_source, "created_by") and external_data_source.created_by:
        created_by_user_id = str(external_data_source.created_by.id)
        created_by_user_email = external_data_source.created_by.email
        created_by_user_name = (
            f"{external_data_source.created_by.first_name} {external_data_source.created_by.last_name}".strip()
        )

    return created_by_user_id, created_by_user_email, created_by_user_name
