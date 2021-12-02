from typing import Dict, Optional

import psycopg2.sql

# Singleton which holds information about the current request/celery task. Modify this to update comments
# for clickhouse and postgresql queries
request_information: Optional[Dict] = None


def execute_pg_query_with_logging(execute, sql, *args, **kwargs):
    """
    Executes the query with a comment with request information prepended. This is useful for debugging during incidents.

    Install this via connection.execute_wrappers.append(execute_pg_query_with_logging) in a @receiver(connection_created) hook.
    """

    if isinstance(sql, psycopg2.sql.SQL):
        sql = sql.string

    return execute(f"{sql_comment()}{sql}", *args, **kwargs)


def sql_comment():
    "Returns a SQL comment with the current request information"

    if request_information is not None:
        return f"/* {request_information['kind']}:{request_information['id'].replace('/', '_')} */ "
    else:
        return ""
