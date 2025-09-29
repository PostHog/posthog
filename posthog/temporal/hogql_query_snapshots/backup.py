from posthog.temporal.hogql_query_snapshots.delta_snapshot import DeltaSnapshot
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.s3 import get_s3_client


def create_backup_object(saved_query: DataWarehouseSavedQuery) -> None:
    s3 = get_s3_client()

    delta_snapshot = DeltaSnapshot(saved_query)
    original_folder = delta_snapshot._get_delta_table_uri()
    backup_folder = delta_snapshot.backup_delta_table_uri

    s3.copy(original_folder, backup_folder, recursive=True)


def restore_from_backup(saved_query: DataWarehouseSavedQuery) -> None:
    s3 = get_s3_client()
    delta_snapshot = DeltaSnapshot(saved_query)
    original_folder = delta_snapshot._get_delta_table_uri()
    backup_folder = delta_snapshot.backup_delta_table_uri
    if not s3.exists(backup_folder):
        raise FileNotFoundError(f"Backup folder does not exist: {backup_folder}")
    s3.copy(backup_folder, original_folder, recursive=True)


def clear_backup_object(saved_query: DataWarehouseSavedQuery) -> None:
    s3 = get_s3_client()
    delta_snapshot = DeltaSnapshot(saved_query)
    backup_folder = delta_snapshot.backup_delta_table_uri
    s3.delete(backup_folder, recursive=True)
