import os
from typing import Any, Callable, List, Optional, Set

from django.core.exceptions import ImproperlyConfigured

from posthog.utils import str_to_bool

__all__ = ["get_from_env", "get_list", "str_to_bool"]


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


def get_list(text: str) -> List[str]:
    if not text:
        return []
    return [item.strip() for item in text.split(",")]


def get_set(text: str) -> Set[str]:
    if not text:
        return set()
    return {item.strip() for item in text.split(",")}
