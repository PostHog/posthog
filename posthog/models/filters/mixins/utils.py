from functools import lru_cache
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# can't use cached_property directly from functools because of 3.7 compatibilty
def cached_property(func: Callable[..., T]) -> T:
    return property(lru_cache(maxsize=1)(func))  # type: ignore


def include_dict(f):
    f.include_dict = True
    return f
