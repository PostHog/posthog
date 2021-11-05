import inspect
import pprint
from string import Formatter
from typing import Any, Dict, Tuple


class UnsafeSQLInterpolationError(ValueError):
    "Indicates some illegal SQL interpolation has occurred"
    pass


class SQL:
    """
    Class help with SQL query building.

    Features:
    - Keeps query and query parameters in a single class
    - Handles interpolation of various query fragments
    - Disallows unsafe interpolation of client-passed values.
    - Automatically pulls in values from parent scope

    Example usage:
        subquery = SQL("SELECT * FROM events WHERE timestamp > %(ts)s", params={"ts": "2021-11-02"})
        main_query = SQL("SELECT max(timestamp) FROM ({subquery})")

    To execute the query:
        sync_execute(main_query)
    """

    def __init__(self, query: str, params: Dict[str, Any] = {}, **kwargs):
        if len(kwargs) == 0:
            # :TRICKY: Automatically access values from parent scope.
            #   This avoids needing to write `subquery` 3 times in the above example
            locals = inspect.currentframe().f_back.f_locals  # type: ignore
        self.query, self.params = self.format(query, params, locals)

    def format(self, query: str, params: Dict[str, Any], locals: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Parse a string formatting expression for SQL building and return the "built" query, accounting for query params.

        May throw if interpolating non-safe values.
        """

        result_query, result_params = [], {}
        for static_string, format_expression, _format_spec, _conversion in Formatter().parse(query):
            result_query.append(static_string)

            if format_expression is None:
                continue
            elif format_expression not in locals:
                raise NameError(f"name {repr(format_expression)} is not defined")

            interpolated_value = locals[format_expression]
            if not isinstance(interpolated_value, SQL):
                raise UnsafeSQLInterpolationError(
                    f"Cannot safely interpolate {repr(format_expression)}, expecting type SQL, got {type(interpolated_value)}."
                    "\n\nIf the value is safe to interpolate, wrap it using SQL()"
                )

            result_query.append(interpolated_value.query)
            result_params.update(interpolated_value.params)

        result_params.update(params)

        return "".join(result_query), result_params

    def __repr__(self):
        return f"SQL{pprint.pformat((self.query, self.params))}"


# Convenience type for some functions
SQLFragment = SQL
