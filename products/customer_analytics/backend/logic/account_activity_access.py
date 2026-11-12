from uuid import UUID

from django.core.exceptions import ValidationError

from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.customer_analytics.backend.models import Account


def get_account_activity_account(
    *, team: Team, user: object, account_id: str, access: UserAccessControl | None = None
) -> Account:
    if not isinstance(user, User):
        raise UserAccessControlError("account", "viewer", resource_id=account_id)
    access = access if access is not None else UserAccessControl(user=user, team=team)
    access.assert_access_level_for_resource("account", "viewer")
    access.assert_access_level_for_resource("person", "viewer")
    visible = access.filter_queryset_by_access_level(Account.objects.for_team(team.id), resource="account")
    try:
        account = visible.filter(id=UUID(account_id)).only("id", "external_id").first()
    except (ValidationError, ValueError):
        account = None
    if account is None:
        raise UserAccessControlError("account", "viewer", resource_id=account_id)
    return account
