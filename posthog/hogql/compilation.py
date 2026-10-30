import time
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from typing import ParamSpec, TypeVar

from posthog.hogql.errors import QueryError

MAX_VIEW_DEPTH = 100
MAX_VIEW_EXPANSIONS = 1000
MAX_EXPANDED_VIEW_SQL_BYTES = 4 * 1024 * 1024
COMPILATION_TIMEOUT_SECONDS = 60.0


class CompilationBudget:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + COMPILATION_TIMEOUT_SECONDS
        self.view_expansions = 0
        self.expanded_view_sql_bytes = 0

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise QueryError("HogQL compilation exceeded its time limit. Simplify the query and try again.")

    def expand_view(self, query: str) -> None:
        self.check_time()
        if self.view_expansions >= MAX_VIEW_EXPANSIONS:
            raise QueryError(
                f"Query exceeds the limit of {MAX_VIEW_EXPANSIONS} saved view expansions. "
                "Reduce the number of saved view references."
            )
        query_bytes = len(query.encode("utf-8"))
        if self.expanded_view_sql_bytes + query_bytes > MAX_EXPANDED_VIEW_SQL_BYTES:
            raise QueryError(
                "Query exceeds the saved view SQL expansion size limit. "
                "Reduce the size or number of referenced saved views."
            )
        self.view_expansions += 1
        self.expanded_view_sql_bytes += query_bytes


# Nested compilers and transforms must share the outer request's budget, including
# visitors that do not carry a HogQLContext. ContextVar keeps concurrent requests isolated.
compilation_budget: ContextVar[CompilationBudget | None] = ContextVar("hogql_compilation_budget", default=None)

P = ParamSpec("P")
R = TypeVar("R")


def bounded_compilation(function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        budget = compilation_budget.get()
        token = None
        if budget is None:
            budget = CompilationBudget()
            token = compilation_budget.set(budget)
        try:
            budget.check_time()
            result = function(*args, **kwargs)
            budget.check_time()
            return result
        except RecursionError as error:
            raise QueryError(
                "HogQL query exceeds the supported nesting depth. Reduce nested subqueries or saved views."
            ) from error
        finally:
            if token is not None:
                compilation_budget.reset(token)

    return wrapped
