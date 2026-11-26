from posthog.schema import HogQLQueryResponse

from posthog.hogql.query import HogQLQueryExecutor, hogql_execution_override


def execute_in_process(*args, **kwargs) -> HogQLQueryResponse:
    executor = HogQLQueryExecutor(*args, **kwargs)
    override = hogql_execution_override.get()
    return override(executor) if override is not None else executor.execute()
