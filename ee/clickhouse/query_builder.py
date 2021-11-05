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
        TABLE_NAME = "events"
        subquery = SQL("SELECT * FROM {TABLE_NAME!s} WHERE timestamp > %(ts)s", params={"ts": "2021-11-02"})
        main_query = SQL("SELECT max(timestamp) FROM ({subquery})")

    To execute the query:
        sync_execute(main_query)
    """

    SAFE_CONVERSION = "s"

    def __init__(self, query: str, params: Dict[str, Any] = {}):
        # :TRICKY: Automatically access values from parent scope.
        #   This avoids needing to write `subquery` 3 times in the above example
        parent_frame = inspect.currentframe().f_back
        globals = parent_frame.f_globals  # type: ignore
        locals = parent_frame.f_locals  # type: ignore

        self.query, self.params = self.format(query, params, globals, locals)

    def format(
        self, query: str, params: Dict[str, Any], globals: Dict[str, Any] = {}, locals: Dict[str, Any] = {}
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Parse a string formatting expression for SQL building and return the "built" query, accounting for query params.

        May throw if interpolating non-safe values.
        """

        result_query, result_params = [], {}
        for static_string, format_expression, _format_spec, conversion in Formatter().parse(query):
            result_query.append(static_string)

            if format_expression is None:
                continue
            # elif format_expression not in locals:
            #     raise NameError(f"name {repr(format_expression)} is not defined")

            interpolated_value = eval(format_expression, globals, locals)

            if isinstance(interpolated_value, SQL):
                result_query.append(interpolated_value.query)
                result_params.update(interpolated_value.params)
            elif conversion == self.SAFE_CONVERSION:
                result_query.append(interpolated_value)
            else:
                raise UnsafeSQLInterpolationError(
                    f"Cannot safely interpolate {repr(format_expression)}, expecting type SQL, got {type(interpolated_value)}."
                    "\n\nIf the value is safe to interpolate, wrap it using SQL() or using {expression!s}"
                )

        result_params.update(params)

        return "".join(result_query), result_params

    def __repr__(self):
        return f"SQL{pprint.pformat((self.query, self.params))}"

    def query_and_params(self) -> Tuple[str, Dict[str, Any]]:
        return self.query, self.params


# Convenience type for some functions
SQLFragment = SQL
