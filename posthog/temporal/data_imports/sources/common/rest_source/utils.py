"""Utility functions for REST API sources."""

import logging
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

logger = logging.getLogger(__name__)


def join_url(base_url: str, path: str) -> str:
    """Join base URL and path."""
    if not base_url.endswith("/"):
        base_url += "/"
    return base_url + path.lstrip("/")


def exclude_keys(d: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """Removes specified keys from a dictionary and returns a new dictionary.

    Args:
        d: The dictionary to remove keys from.
        keys: The keys to remove.

    Returns:
        A new dictionary with the specified keys removed.
    """
    return {k: v for k, v in d.items() if k not in keys}


def check_connection(
    source: Iterator[dict[str, Any]],
    *resource_names: str,
) -> tuple[bool, str]:
    """Check connection by trying to fetch first item from source.

    Args:
        source: Resource iterator
        resource_names: Resource names (not used in simplified version)

    Returns:
        Tuple of (success, error_message)
    """
    try:
        # Try to get first item
        next(iter(source))
        return (True, "")
    except Exception as e:
        logger.exception("Error checking connection")
        return (False, str(e))
