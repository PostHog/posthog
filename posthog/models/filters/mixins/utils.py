from typing import Optional, TypeVar, Union

from posthog.utils import str_to_bool

T = TypeVar("T")


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
