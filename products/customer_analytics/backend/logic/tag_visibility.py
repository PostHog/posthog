from django.db.models import Exists, Q

from posthog.models.tag_visibility import TagVisibilityContext

from products.customer_analytics.backend.logic.customer_tasks import filter_visible_accounts
from products.customer_analytics.backend.models import CustomerTask


def customer_task_on_visible_account(context: TagVisibilityContext) -> Exists:
    visible_account_ids = filter_visible_accounts(context.team_id, context.user_access_control).values("id")
    return Exists(
        CustomerTask.objects.for_team(context.team_id)
        .filter(pk=context.object_ref)
        .filter(Q(account__isnull=True) | Q(account_id__in=visible_account_ids))
    )


def account_note_on_visible_account(context: TagVisibilityContext) -> Exists:
    # One filter() call, so the note checks apply to the same account link that matched the notebook.
    return Exists(
        filter_visible_accounts(context.team_id, context.user_access_control).filter(
            notebooks__notebook_id=context.object_ref,
            notebooks__notebook__visibility="internal",
            notebooks__notebook__deleted=False,
        )
    )
