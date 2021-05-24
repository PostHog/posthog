# TODO: move to ee/
from typing import Dict, List

from posthog.ee import is_clickhouse_enabled


def get_backup_info() -> Dict:
    # TODO fill with actual data
    return {"is_enabled": is_enabled(), "existing_backups": get_existing_backup_names()}


def is_enabled() -> bool:
    return is_clickhouse_enabled()  # TODO more specofic backup related setup


def get_existing_backup_names() -> List[str]:
    return ["bk1", "bk2", "bk333"]
