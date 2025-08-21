from typing import Optional


def get_batch_export_destination_type(batch_export) -> str:
    """Get destination type from BatchExport"""
    destination_type = ""
    try:
        if batch_export.destination:
            destination_type = batch_export.destination.type
    except Exception:
        destination_type = "unknown"
    return destination_type


def get_batch_export_created_by_info(batch_export) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Get created by user information from BatchExport"""
    created_by_user_id = None
    created_by_user_email = None
    created_by_user_name = None

    if hasattr(batch_export, "created_by") and batch_export.created_by:
        created_by_user_id = str(batch_export.created_by.id)
        created_by_user_email = batch_export.created_by.email
        created_by_user_name = f"{batch_export.created_by.first_name} {batch_export.created_by.last_name}".strip()

    return created_by_user_id, created_by_user_email, created_by_user_name


def get_batch_export_detail_name(batch_export, destination_type: str) -> str:
    """Generate detail name for BatchExport activity"""
    name = batch_export.name or "Unnamed Export"
    return f"'{name}' ({destination_type})"
