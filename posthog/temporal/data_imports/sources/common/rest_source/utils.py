from collections.abc import Iterable, Mapping
from typing import Any

from dlt.common import logger
from dlt.extract.source import DltSource


def join_url(base_url: str, path: str) -> str:
    if not base_url.endswith("/"):
        base_url += "/"
    return base_url + path.lstrip("/")


def exclude_keys(d: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Removes specified keys from a dictionary and returns a new dictionary.

    Args:
        d (Mapping[str, Any]): The dictionary to remove keys from.
        keys (Iterable[str]): The keys to remove.

    Returns:
        Dict[str, Any]: A new dictionary with the specified keys removed.
    """
    return {k: v for k, v in d.items() if k not in keys}


def check_connection(
    source: DltSource,
    *resource_names: str,
) -> tuple[bool, str]:
    try:
        list(source.with_resources(*resource_names).add_limit(1))
        return (True, "")
    except Exception as e:
        logger.error(f"Error checking connection: {e}")
        return (False, str(e))
