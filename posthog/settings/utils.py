import os
import importlib
from typing import Any, Callable, List, Optional

from django.core.exceptions import ImproperlyConfigured

from posthog.utils import str_to_bool

__all__ = ["get_from_env", "get_list", "str_to_bool"]


def get_from_env(key: str, default: Any = None, *, optional: bool = False, type_cast: Optional[Callable] = None) -> Any:
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


def str_to_class(path: str) -> type:
    """Take a string like posthog.models.person.Person and turn it into a class

    Django provides a super useful function to do this! get_model. However, it requires
    that models are loaded. I'd like to load the class up-front, which happens before the
    models are loaded. Otherwise, we'd need to do so _after_ the dbrouter is instantiated,
    which isn't great.
    """

    # We need to determine the module portion of the path, and the classname portion
    parts = path.split(".")

    if len(parts) <= 1:
        raise RuntimeError("Unexpected empty class path; expected posthog.module.path.Class")

    module_path = ".".join(parts[:-1])
    class_name = parts[-1]

    module = importlib.import_module(module_path)
    class_obj = getattr(module, class_name)

    return class_obj
