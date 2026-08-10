from typing import NoReturn
from uuid import UUID

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AccountsTableAccountFieldColumn,
    AccountsTableCustomPropertyColumn,
    AccountsTableCustomPropertyHistoryColumn,
    AccountsTableCustomPropertyHistoryPoint,
    AccountsTableNoteCountColumn,
    AccountsTableQuery,
    AccountsTableQueryResponse,
    AccountsTableRelationshipColumn,
    AccountsTableRow,
    AccountsTableTagsColumn,
    CachedAccountsTableQueryResponse,
)

from posthog.hogql.constants import get_default_limit_for_context, get_max_limit_for_context

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import User
from posthog.rbac.user_access_control import UserAccessControl, UserAccessControlError

from products.customer_analytics.backend.facade import api, contracts

ACCOUNTS_TABLE_MAX_COLUMNS = 100
ACCOUNTS_TABLE_MAX_PAGE_SIZE = 500


class AccountsTableQueryRunner(AnalyticsQueryRunner[AccountsTableQueryResponse]):
    query: AccountsTableQuery
    cached_response: CachedAccountsTableQueryResponse

    def validate_query_runner_access(self, user: User) -> bool:
        return UserAccessControl(user=user, team=self.team).assert_access_level_for_resource("account", "viewer")

    def to_query(self) -> NoReturn:
        raise NotImplementedError("AccountsTableQueryRunner executes against Postgres")

    def _column_selection(self) -> contracts.AccountTableColumnSelection:
        if len(self.query.columns) > ACCOUNTS_TABLE_MAX_COLUMNS:
            raise ValidationError(f"Account table queries support up to {ACCOUNTS_TABLE_MAX_COLUMNS} columns.")

        account_fields: set[contracts.AccountTableField] = set()
        include_tags = False
        include_note_count = False
        relationship_definition_ids: set[UUID] = set()
        custom_property_definition_ids: set[UUID] = set()
        custom_property_history_windows: dict[UUID, int] = {}

        try:
            for column in self.query.columns:
                if isinstance(column, AccountsTableAccountFieldColumn):
                    account_fields.add(contracts.AccountTableField(column.field.value))
                elif isinstance(column, AccountsTableTagsColumn):
                    include_tags = True
                elif isinstance(column, AccountsTableNoteCountColumn):
                    include_note_count = True
                elif isinstance(column, AccountsTableRelationshipColumn):
                    relationship_definition_ids.add(UUID(column.definitionId))
                elif isinstance(column, AccountsTableCustomPropertyColumn):
                    custom_property_definition_ids.add(UUID(column.definitionId))
                elif isinstance(column, AccountsTableCustomPropertyHistoryColumn):
                    definition_id = UUID(column.definitionId)
                    window_days = int(column.windowDays.value)
                    custom_property_history_windows[definition_id] = max(
                        window_days,
                        custom_property_history_windows.get(definition_id, 0),
                    )
        except ValueError as error:
            raise ValidationError("Account table definition IDs must be valid UUIDs.") from error

        return contracts.AccountTableColumnSelection(
            account_fields=frozenset(account_fields),
            include_tags=include_tags,
            include_note_count=include_note_count,
            relationship_definition_ids=frozenset(relationship_definition_ids),
            custom_property_definition_ids=frozenset(custom_property_definition_ids),
            custom_property_history_windows=custom_property_history_windows,
        )

    def _calculate(self) -> AccountsTableQueryResponse:
        user_access_control = self.user_access_control
        if user_access_control is None:
            raise UserAccessControlError("account", "viewer")

        limit = min(
            self.query.limit or get_default_limit_for_context(self.limit_context),
            get_max_limit_for_context(self.limit_context),
            ACCOUNTS_TABLE_MAX_PAGE_SIZE,
        )
        offset = max(self.query.offset or 0, 0)

        try:
            page = api.query_accounts_table(
                team_id=self.team.id,
                user_access_control=user_access_control,
                selection=self._column_selection(),
                offset=offset,
                limit=limit,
            )
        except api.InvalidAccountTableColumn as error:
            raise ValidationError(str(error)) from error

        return AccountsTableQueryResponse(
            results=[
                AccountsTableRow(
                    id=str(row.id),
                    name=row.name,
                    externalId=row.external_id,
                    accountFields={field.value: value for field, value in row.account_fields.items()},
                    tags=row.tags,
                    noteCount=row.note_count,
                    relationships={
                        str(definition_id): user_ids for definition_id, user_ids in row.relationships.items()
                    },
                    customProperties={
                        str(definition_id): value for definition_id, value in row.custom_properties.items()
                    },
                    customPropertyHistory={
                        str(definition_id): [
                            AccountsTableCustomPropertyHistoryPoint(timestamp=point.timestamp, value=point.value)
                            for point in points
                        ]
                        for definition_id, points in row.custom_property_history.items()
                    },
                )
                for row in page.rows
            ],
            hasMore=page.has_more,
            limit=page.limit,
            offset=page.offset,
        )
