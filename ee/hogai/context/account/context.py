from django.core.exceptions import ObjectDoesNotExist

from posthog.models import Team, User
from posthog.models.group.util import get_group_by_key
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from products.customer_analytics.backend.facade.api import get_account_context_data
from products.customer_analytics.backend.facade.constants import (
    BILLING_SPEND_INSIGHT_SHORT_IDS,
    BILLING_USAGE_INSIGHT_SHORT_IDS,
)
from products.customer_analytics.backend.facade.contracts import AccountContextData

from .prompts import (
    ACCOUNT_ANALYSIS_CONNECTED_TEMPLATE,
    ACCOUNT_ANALYSIS_GROUP_NOT_FOUND_TEMPLATE,
    ACCOUNT_ANALYSIS_NO_EXTERNAL_ID_TEMPLATE,
    ACCOUNT_ANALYSIS_NOT_CONFIGURED_TEMPLATE,
    ACCOUNT_CONTEXT_TEMPLATE,
    ACCOUNT_EXTERNAL_IDS_TEMPLATE,
    ACCOUNT_NOT_FOUND_TEMPLATE,
    ACCOUNT_NOTES_TEMPLATE,
    ACCOUNT_ROLES_TEMPLATE,
    ACCOUNT_TAGS_TEMPLATE,
)

_ROLE_LABELS = [("CSM", "csm"), ("Account executive", "account_executive"), ("Account owner", "account_owner")]
_EXTERNAL_ID_LABELS = [
    ("Stripe customer id", "stripe_customer_id"),
    ("HubSpot deal id", "hubspot_deal_id"),
    ("Billing id", "billing_id"),
    ("Salesforce id", "sfdc_id"),
    ("Zendesk id", "zendesk_id"),
    ("Slack channel id", "slack_channel_id"),
]


class AccountContext:
    """
    Context class for customer accounts used across the assistant.

    Fetches an account and formats it for AI consumption, resolving the account→group link so the
    agent can scope usage and event analysis to the right group.
    """

    def __init__(self, team: Team, user: User, account_id: str | None = None, external_id: str | None = None):
        self._team = team
        self._user = user
        self._account_id = account_id
        self._external_id = external_id

    @property
    def user_access_control(self) -> UserAccessControl:
        return UserAccessControl(user=self._user, team=self._team, organization_id=str(self._team.organization_id))

    async def aget_account(self) -> AccountContextData | None:
        return await database_sync_to_async(get_account_context_data)(
            team_id=self._team.id,
            account_id=self._account_id,
            external_id=self._external_id,
            user_access_control=self.user_access_control,
        )

    def get_not_found_message(self) -> str:
        identifier = f"id={self._account_id}" if self._account_id else f"external_id={self._external_id}"
        return ACCOUNT_NOT_FOUND_TEMPLATE.format(identifier=identifier)

    @database_sync_to_async
    def format_account(self, account: AccountContextData) -> str:
        return ACCOUNT_CONTEXT_TEMPLATE.format(
            name=account.name,
            account_id=str(account.id),
            external_id=account.external_id or "Not set",
            created_at=account.created_at.isoformat() if account.created_at else "Unknown",
            roles_section=self._roles_section(account),
            external_ids_section=self._external_ids_section(account),
            tags_section=self._tags_section(account),
            notes_section=self._notes_section(account),
            analysis_section=self._analysis_section(account),
        ).strip()

    async def execute_and_format(self) -> str:
        account = await self.aget_account()
        if account is None:
            return self.get_not_found_message()
        return await self.format_account(account)

    def _roles_section(self, account: AccountContextData) -> str:
        properties = account.properties
        lines = [
            f"- {label}: {assignment.email} (user {assignment.id})"
            for label, field in _ROLE_LABELS
            if (assignment := getattr(properties, field)) is not None
        ]
        if not lines:
            return ""
        return "\n" + ACCOUNT_ROLES_TEMPLATE.format(roles_list="\n".join(lines))

    def _external_ids_section(self, account: AccountContextData) -> str:
        properties = account.properties
        lines = [f"- {label}: {value}" for label, field in _EXTERNAL_ID_LABELS if (value := getattr(properties, field))]
        if not lines:
            return ""
        return "\n" + ACCOUNT_EXTERNAL_IDS_TEMPLATE.format(ids_list="\n".join(lines))

    def _tags_section(self, account: AccountContextData) -> str:
        if not account.tags:
            return ""
        return "\n" + ACCOUNT_TAGS_TEMPLATE.format(tags_list=", ".join(account.tags))

    def _notes_section(self, account: AccountContextData) -> str:
        lines = [f'- "{note.title}" (short_id: {note.short_id})' for note in account.notes]
        if not lines:
            return ""
        return "\n" + ACCOUNT_NOTES_TEMPLATE.format(notes_list="\n".join(lines))

    def _analysis_section(self, account: AccountContextData) -> str:
        group_type_index = self._account_group_type_index()
        if group_type_index is None:
            return ACCOUNT_ANALYSIS_NOT_CONFIGURED_TEMPLATE
        if not account.external_id:
            return ACCOUNT_ANALYSIS_NO_EXTERNAL_ID_TEMPLATE

        group = get_group_by_key(
            team_id=self._team.id, group_type_index=group_type_index, group_key=account.external_id
        )
        if group is None:
            return ACCOUNT_ANALYSIS_GROUP_NOT_FOUND_TEMPLATE.format(group_key=account.external_id)
        return ACCOUNT_ANALYSIS_CONNECTED_TEMPLATE.format(
            group_type_index=group_type_index,
            group_key=account.external_id,
            billing_insights_clause=self._billing_insights_clause(),
        )

    def _billing_insights_clause(self) -> str:
        usage = ", ".join(BILLING_USAGE_INSIGHT_SHORT_IDS)
        spend = ", ".join(BILLING_SPEND_INSIGHT_SHORT_IDS)
        return f" (Usage insight short ids: {usage}; Spend insight short ids: {spend})"

    def _account_group_type_index(self) -> int | None:
        try:
            return self._team.customer_analytics_config.account_group_type_index
        except ObjectDoesNotExist:
            return None
