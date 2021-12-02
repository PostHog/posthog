# Wraps the default django.db.backends.postgresql database wrapper, but adds comments to queries being executed

from typing import Dict, Optional

request_information: Optional[Dict] = None


def execute_pg_query_with_logging(execute, sql, *args, **kwargs):
    """
    Executes the query with a comment with request information prepended.

    Install this via connection.execute_wrappers.append
    """

    return execute(f"{sql_comment()}{sql}", *args, **kwargs)


def sql_comment():
    if request_information is not None:
        return f"/* {request_information['kind']}:{request_information['id'].replace('/', '_')} */ "
    else:
        return ""
