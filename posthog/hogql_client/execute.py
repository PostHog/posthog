from posthog.schema import HogQLQueryResponse

from posthog.hogql_service.execute import execute_in_process


def execute_hogql_query(*args, **kwargs) -> HogQLQueryResponse:
    return execute_in_process(*args, **kwargs)
