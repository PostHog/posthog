from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import connection, transaction

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade.contracts import CreateCustomerTaskInput, CustomerTaskAccessDenied
from products.customer_analytics.backend.logic.customer_tasks import create_customer_task, get_customer_task
from products.customer_analytics.backend.models import CustomerTask


def create_workflow_customer_task(
    *,
    team: Team,
    workflow_id: UUID,
    idempotency_key: str,
    input: CreateCustomerTaskInput,
    actor: User,
    user_access_control: UserAccessControl,
) -> UUID:
    if not user_access_control.has_project_access or not user_access_control.check_access_level_for_resource(
        "customer_task", "editor"
    ):
        raise CustomerTaskAccessDenied()
    task_id = uuid5(NAMESPACE_URL, f"posthog:customer-task:{team.id}:{workflow_id}:{idempotency_key}")
    with transaction.atomic():
        # Lock the invocation even before its task exists, so concurrent retries create one activity and assignment.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [team.id, str(task_id)])
        if CustomerTask.objects.for_team(team.id).filter(id=task_id).exists():
            if get_customer_task(team_id=team.id, task_id=task_id, user_access_control=user_access_control) is None:
                raise CustomerTaskAccessDenied()
            return task_id
        task = create_customer_task(
            team=team, input=input, actor=actor, user_access_control=user_access_control, task_id=task_id
        )
        return task.id
