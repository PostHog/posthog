from functools import lru_cache
from typing import Callable, Optional, TypeVar, Union

from posthog.utils import str_to_bool

T = TypeVar("T")

# can't use cached_property directly from functools because of 3.7 compatibilty
def cached_property(func: Callable[..., T]) -> T:
    return property(lru_cache(maxsize=1)(func))  # type: ignore


def include_dict(f):
    f.include_dict = True
    return f


def process_bool(bool_to_test: Optional[Union[str, bool]]) -> bool:
    if isinstance(bool_to_test, bool):
        return bool_to_test
    elif isinstance(bool_to_test, str):
        return str_to_bool(bool_to_test)
    else:
        return False
