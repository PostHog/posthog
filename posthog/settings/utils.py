import os
import re
from collections.abc import Callable
from hashlib import sha1
from typing import Any, Optional

from django.core.exceptions import ImproperlyConfigured

from posthog.utils import str_to_bool

__all__ = ["build_postgres_test_db_name", "get_from_env", "get_list", "str_to_bool"]

POSTGRES_IDENTIFIER_MAX_LENGTH = 63


def get_from_env(
    key: str,
    default: Any = None,
    *,
    optional: bool = False,
    type_cast: Optional[Callable] = None,
) -> Any:
    value = os.getenv(key)
    if value is None or value == "":
        if optional:
            return None
        if default is not None:
            return default
        else:
            raise ImproperlyConfigured(f'The environment variable "{key}" is required to run PostHog!')
    if type_cast is not None:
        return type_cast(value)
    return value


def get_list(text: str) -> list[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(",")]


def get_set(text: str) -> set[str]:
    if not text:
        return set()
    return {item.strip() for item in text.split(",")}


def build_postgres_test_db_name(base_name: str, *, suffix: str = "") -> str:
    normalized_base_name = re.sub(r"^(test_)+", "", base_name)
    candidate = f"test_{normalized_base_name}{suffix}"
    if len(candidate) <= POSTGRES_IDENTIFIER_MAX_LENGTH:
        return candidate

    digest = sha1(candidate.encode("utf-8")).hexdigest()[:10]
    available_base_chars = POSTGRES_IDENTIFIER_MAX_LENGTH - len("test__") - len(digest) - len(suffix)
    truncated_base_name = normalized_base_name[: max(1, available_base_chars)]
    return f"test_{truncated_base_name}_{digest}{suffix}"
