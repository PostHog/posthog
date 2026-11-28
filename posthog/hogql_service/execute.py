from typing import Any

from django.contrib.auth.models import AnonymousUser

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.query import HogQLQueryExecutor, hogql_execution_override
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_client.contract import ExecuteRequest
from posthog.models import Team, User
from posthog.synthetic_user import SyntheticUser

from products.access_control.backend.facade.user_access_control import UserAccessControl


def execute_in_process(*args, **kwargs) -> HogQLQueryResponse:
    executor = HogQLQueryExecutor(*args, **kwargs)
    override = hogql_execution_override.get()
    return override(executor) if override is not None else executor.execute()


def execute_request(request: ExecuteRequest, team_id: int, user_id: int | None) -> HogQLQueryResponse:
    team = Team.objects.get(pk=team_id)
    user = User.objects.get(pk=user_id) if user_id is not None else None
    arguments = request.executor_arguments()
    if request.context is not None:
        arguments["context"] = request.context.to_context(team_id=team.pk, user=user)
    return execute_in_process(request.query, team, user=user, **arguments)


def execute_through_request(
    query: str | ast.SelectQuery | ast.SelectSetQuery | None,
    team: Team,
    *,
    user: User | AnonymousUser | SyntheticUser | None = None,
    user_access_control: UserAccessControl | None = None,
    timings: HogQLTimings | None = None,
    **arguments: Any,
) -> HogQLQueryResponse:
    if user is not None and not isinstance(user, User):
        raise ValueError(f"A {type(user).__name__} principal has no wire form")
    request = ExecuteRequest.from_call(query, **arguments)
    response = execute_request(
        ExecuteRequest.model_validate_json(request.to_json()),
        team_id=team.pk,
        user_id=user.pk if user is not None else None,
    )
    if timings is not None:
        timings.include(response.timings or [])
        response.timings = timings.to_list()
    return response
