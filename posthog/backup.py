# TODO: move to ee/
import json
from typing import Dict, List, Tuple

import requests

from posthog.ee import is_clickhouse_enabled

URL_BASE = "http://clickhouse:7171/backup"


def get_backup_info() -> Dict:
    # TODO fill with actual data
    return {"is_enabled": is_enabled(), "existing_backups": get_existing_backup_names()}


def is_enabled() -> bool:
    return is_clickhouse_enabled()  # TODO more specofic backup related setup


def get_existing_backup_names() -> List[str]:
    if not is_enabled():
        return []
    # TODO: error handling etc
    url = f"{URL_BASE}/list"
    response = requests.get(url)
    items = response.text.split("\n")[:-1]  # to ignore the '' last one from linebreak
    names = [json.loads(i)["name"] for i in items]
    return names


def get_status() -> List[str]:
    if not is_enabled():
        return []
    # TODO: make a refresh button
    url = f"{URL_BASE}/status"
    response = requests.get(url)
    items = response.text.split("\n")[:-1]  # to ignore the '' last one from linebreak
    res = [json.loads(i) for i in reversed(items)]
    print(res)
    return res


def create_backup(name: str) -> Tuple[int, str]:
    url = f"{URL_BASE}/create?name={name}"
    response = requests.post(url)
    print(f"Created backup with {name}")
    return int(response.status_code), str(response.json()) if response.ok else ""  # only if response is good


def restore_from_backup(name: str) -> Tuple[int, str]:
    url = f"{URL_BASE}/restore/{name}"
    response = requests.post(url)
    print(f"Restored from backup with {name}")
    return int(response.status_code), str(response.json()) if response.ok else ""  # only if response is good
