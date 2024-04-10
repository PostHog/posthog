# Methods used for rendering a ClickHouse query, given a template string and a
# set of parameters.
#
# This uses the `escape_param` function from the `clickhouse-driver` package,
# but passes an empty `Context` object to it. Prior to
# https://github.com/mymarilyn/clickhouse-driver/commit/87090902f0270ed51a0b6754d5cbf0dc8544ec4b
# the `escape_param` function didn't take a `Context` object. As of
# `clickhouse-driver` 0.2.4 all it uses the context for is to determine the
# "server" timezone, so passing an empty context maintains the existing
# behaviour of `clickhouse-driver` 0.2.1, the version we were previously using.
#
# This is of course a bit of a hack but we want to be able to render queries
# without the need of having a connection, which seems like a reasonable thing
# to be able to do. Having a dependency on a connection to render a query is a
# little over the top.
#
# NOTE: this change is necessary because the `clickhouse-driver` package up to
# 0.2.3 uses an invalid `python_requires` in it's `setup.py` at least for
# recent versions of setuptools. This was highlighted as a consequence of
# upgrading to Python 3.10. See
# https://github.com/mymarilyn/clickhouse-driver/pull/291 for further context.


from typing import Any

from clickhouse_driver.connection import ServerInfo
from clickhouse_driver.context import Context
from clickhouse_driver.util.escape import escape_param


def substitute_params(query, params):
    """
    This is a copy of clickhouse-driver's `substitute_params` function without
    the dependency that you need to connect to the server before you can escape
    params. There was a bug in which we were trying to substitute params before
    the connection was established, which caused the query to fail. Presumably
    this was on initial worker startup only.

    It seems somewhat unusual that you need to connect to the server before
    you can escape params, so we're just going to copy the function here
    and remove that dependency.

    See
    https://github.com/mymarilyn/clickhouse-driver/blob/87090902f0270ed51a0b6754d5cbf0dc8544ec4b/clickhouse_driver/client.py#L593
    for the original function.
    """
    if not isinstance(params, dict):
        raise ValueError("Parameters are expected in dict form")

    escaped = escape_params(params)
    return query % escaped


def escape_params(params):
    """
    This is a copy of clickhouse-driver's `escape_params` function without the
    dependency that you need to connect to the server before you can escape
    params.

    See
    https://github.com/mymarilyn/clickhouse-driver/blob/87090902f0270ed51a0b6754d5cbf0dc8544ec4b/clickhouse_driver/util/escape.py#L60
    for the original function.
    """
    escaped = {}

    for key, value in params.items():
        escaped[key] = escape_param_for_clickhouse(value)

    return escaped


def escape_param_for_clickhouse(param: Any) -> str:
    """
    This is a wrapper around the `escape_param` function from the
    `clickhouse-driver` package, but passes a placeholder `Context` object to it
    just such that it can run. The only value that the real `escape_param` uses
    from the context is the server timezone. We assume that the server timezone
    is UTC.

    See
    https://github.com/mymarilyn/clickhouse-driver/blob/87090902f0270ed51a0b6754d5cbf0dc8544ec4b/clickhouse_driver/util/escape.py#L31
    for the wrapped function.
    """
    context = Context()
    context.server_info = ServerInfo(
        name="placeholder server_info value",
        version_major="placeholder server_info value",
        version_minor="placeholder server_info value",
        version_patch="placeholder server_info value",
        revision="placeholder server_info value",
        display_name="placeholder server_info value",
        used_revision="placeholder server_info value",
        timezone="UTC",
    )
    return escape_param(param, context=context)
