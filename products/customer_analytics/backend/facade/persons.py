from posthog.models import Team, User
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade.contracts import (
    AccountPersonsOptions,
    AccountPersonsPage,
    AccountPersonsPropertyAccessError,
)
from products.customer_analytics.backend.logic.account_persons import AccountPersonsReader

__all__ = [
    "AccountPersonsOptions",
    "AccountPersonsPropertyAccessError",
    "list_account_persons",
]


def list_account_persons(
    *, team: Team, user: User, account_id: str, user_access_control: UserAccessControl, options: AccountPersonsOptions
) -> AccountPersonsPage | None:
    reader = AccountPersonsReader.create(
        team=team, user=user, account_id=account_id, user_access_control=user_access_control
    )
    if reader is None:
        return None
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
    restricted_properties = split_restricted_property_names(restrictions).person
    with slo_operation(
        spec=SloSpec(
            distinct_id=str(user.distinct_id),
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.ACCOUNT_PERSONS_LIST,
            team_id=team.pk,
        ),
        properties={
            "product": "customer_analytics",
            "target_duration_ms": 500,
            "selected_property_count": len(set(options.properties) - restricted_properties),
            "has_filters": bool(options.filters),
            "has_search": bool(options.search.strip()),
        },
    ) as slo:
        try:
            page = reader.list_persons(options, restricted_properties)
        except Exception:
            slo.tag(error_message="Account persons query failed.")
            raise
        slo.tag(result_count=len(page.results))
        return page
