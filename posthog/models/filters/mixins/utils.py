from collections.abc import Callable
from functools import lru_cache
from typing import Optional, TypeVar, Union

from posthog.utils import str_to_bool

T = TypeVar("T")


# Each decorated function gets one cache slot. Every instance in the process shares it. The slot keys
# on the instance's __hash__ and __eq__, so a class that compares by value, such as a Django model,
# gets the result that another equal instance cached. Use functools.cached_property instead.
def cached_property(func: Callable[..., T]) -> T:
    return property(lru_cache(maxsize=1)(func))  # type: ignore


def include_dict(f):
    f.include_dict = True
    return f


def include_query_tags(f):
    """
    Decorates a method and adds the result of it to query tags stored in `log_comment`
    in system.query_log when querying insights.

    To get access to these tags, you might need to modify `metrics_query_log` schema.
    """
    f.include_query_tags = True
    return f


def process_bool(bool_to_test: Optional[Union[str, bool]]) -> bool:
    if isinstance(bool_to_test, bool):
        return bool_to_test
    elif isinstance(bool_to_test, str):
        return str_to_bool(bool_to_test)
    else:
        return False
