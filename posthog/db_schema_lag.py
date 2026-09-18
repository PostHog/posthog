import psycopg


def is_schema_lag_error(error: Exception) -> bool:
    """True when the database lacks a column or table this code already knows about.

    A deploy that lands an image before its migration produces this, and it clears itself once
    the migration runs, so callers recover on a later run instead of failing the whole run.
    """
    return isinstance(error.__cause__, psycopg.errors.UndefinedColumn | psycopg.errors.UndefinedTable)
