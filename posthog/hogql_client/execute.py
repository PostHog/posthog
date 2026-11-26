from django.conf import settings

from posthog.schema import HogQLQueryResponse

from posthog.hogql_service.execute import execute_in_process, execute_through_request


def execute_hogql_query(*args, **kwargs) -> HogQLQueryResponse:
    if settings.HOGQL_EXECUTE_THROUGH_REQUEST:
        return execute_through_request(*args, **kwargs)
    return execute_in_process(*args, **kwargs)
