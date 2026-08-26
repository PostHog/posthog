from typing import NoReturn
from uuid import UUID

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AccountsTableAccountFieldColumn,
    AccountsTableAccountFieldFilter,
    AccountsTableAccountIdFilter,
    AccountsTableAggregateMetric,
    AccountsTableAssignedToFilter,
    AccountsTableCountMetric,
    AccountsTableCountThresholdMetric,
    AccountsTableCustomPropertyColumn,
    AccountsTableCustomPropertyFilter,
    AccountsTableCustomPropertyHistoryColumn,
    AccountsTableCustomPropertyHistoryPoint,
    AccountsTableNoteCountColumn,
    AccountsTableQuery,
    AccountsTableQueryResponse,
    AccountsTableRelationshipColumn,
    AccountsTableRow,
    AccountsTableSearchFilter,
    AccountsTableTagsColumn,
    AccountsTableTagsFilter,
    AccountsTableUnassignedFilter,
    CachedAccountsTableQueryResponse,
)

from posthog.hogql.constants import get_default_limit_for_context, get_max_limit_for_context

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import User

from products.access_control.backend.facade.user_access_control import UserAccessControl, UserAccessControlError
from products.customer_analytics.backend.facade import api, contracts

ACCOUNTS_TABLE_MAX_COLUMNS = 100
ACCOUNTS_TABLE_MAX_FILTERS = 50
ACCOUNTS_TABLE_MAX_FILTER_VALUES = 100
ACCOUNTS_TABLE_MAX_METRICS = 5
ACCOUNTS_TABLE_MAX_PAGE_SIZE = 500
ACCOUNTS_TABLE_MAX_STRING_LENGTH = 1_000


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

    def _filters(self) -> tuple[contracts.AccountTableFilter, ...]:
        query_filters = self.query.filters or []
        if len(query_filters) > ACCOUNTS_TABLE_MAX_FILTERS:
            raise ValidationError(f"Account table queries support up to {ACCOUNTS_TABLE_MAX_FILTERS} filters.")

        filters: list[contracts.AccountTableFilter] = []
        try:
            for filter_ in query_filters:
                if (
                    isinstance(filter_, AccountsTableSearchFilter)
                    and len(filter_.query) > ACCOUNTS_TABLE_MAX_STRING_LENGTH
                ):
                    raise ValidationError(
                        f"Account table filter strings support up to {ACCOUNTS_TABLE_MAX_STRING_LENGTH} characters."
                    )
                filter_values = (
                    filter_.tagNames
                    if isinstance(filter_, AccountsTableTagsFilter)
                    else filter_.userIds
                    if isinstance(filter_, AccountsTableAssignedToFilter)
                    else filter_.values or []
                    if isinstance(filter_, AccountsTableAccountFieldFilter | AccountsTableCustomPropertyFilter)
                    else []
                )
                if len(filter_values) > ACCOUNTS_TABLE_MAX_FILTER_VALUES:
                    raise ValidationError(
                        f"Account table filters support up to {ACCOUNTS_TABLE_MAX_FILTER_VALUES} values."
                    )
                if any(
                    isinstance(value, str) and len(value) > ACCOUNTS_TABLE_MAX_STRING_LENGTH for value in filter_values
                ):
                    raise ValidationError(
                        f"Account table filter strings support up to {ACCOUNTS_TABLE_MAX_STRING_LENGTH} characters."
                    )
                if isinstance(filter_, AccountsTableSearchFilter):
                    filters.append(contracts.AccountTableSearchFilter(query=filter_.query))
                elif isinstance(filter_, AccountsTableTagsFilter):
                    filters.append(contracts.AccountTableTagsFilter(tag_names=tuple(filter_.tagNames)))
                elif isinstance(filter_, AccountsTableAssignedToFilter):
                    filters.append(contracts.AccountTableAssignedToFilter(user_ids=tuple(filter_.userIds)))
                elif isinstance(filter_, AccountsTableUnassignedFilter):
                    filters.append(contracts.AccountTableUnassignedFilter())
                elif isinstance(filter_, AccountsTableAccountIdFilter):
                    filters.append(contracts.AccountTableAccountIdFilter(account_id=UUID(filter_.accountId)))
                elif isinstance(filter_, AccountsTableAccountFieldFilter):
                    filters.append(
                        contracts.AccountTableFieldFilter(
                            field=contracts.AccountTableField(filter_.field.value),
                            operator=contracts.AccountTableFieldOperator(filter_.operator.value),
                            values=tuple(filter_.values or ()),
                        )
                    )
                elif isinstance(filter_, AccountsTableCustomPropertyFilter):
                    filters.append(
                        contracts.AccountTableCustomPropertyFilter(
                            definition_id=UUID(filter_.definitionId),
                            operator=contracts.AccountTableCustomPropertyOperator(filter_.operator.value),
                            values=tuple(filter_.values or ()),
                        )
                    )
        except ValueError as error:
            raise ValidationError("Account table filter IDs must be valid UUIDs.") from error
        return tuple(filters)

    def _sort(self) -> contracts.AccountTableSort | None:
        if self.query.sort is None:
            return None

        column = self.query.sort.column
        direction = contracts.AccountTableSortDirection(self.query.sort.direction.value)
        if isinstance(column, AccountsTableAccountFieldColumn):
            return contracts.AccountTableSort(
                kind=contracts.AccountTableSortKind.ACCOUNT_FIELD,
                direction=direction,
                account_field=contracts.AccountTableField(column.field.value),
            )
        if isinstance(column, AccountsTableTagsColumn):
            return contracts.AccountTableSort(kind=contracts.AccountTableSortKind.TAGS, direction=direction)
        if isinstance(column, AccountsTableNoteCountColumn):
            return contracts.AccountTableSort(kind=contracts.AccountTableSortKind.NOTE_COUNT, direction=direction)
        try:
            if isinstance(column, AccountsTableRelationshipColumn):
                return contracts.AccountTableSort(
                    kind=contracts.AccountTableSortKind.RELATIONSHIP,
                    direction=direction,
                    definition_id=UUID(column.definitionId),
                )
            if isinstance(column, AccountsTableCustomPropertyColumn):
                return contracts.AccountTableSort(
                    kind=contracts.AccountTableSortKind.CUSTOM_PROPERTY,
                    direction=direction,
                    definition_id=UUID(column.definitionId),
                )
        except ValueError as error:
            raise ValidationError("Account table sort definition IDs must be valid UUIDs.") from error

    def _metrics(self) -> tuple[contracts.AccountTableMetric, ...]:
        query_metrics = self.query.metrics or []
        if len(query_metrics) > ACCOUNTS_TABLE_MAX_METRICS:
            raise ValidationError(f"Account table queries support up to {ACCOUNTS_TABLE_MAX_METRICS} metrics.")

        metrics: list[contracts.AccountTableMetric] = []
        try:
            for metric in query_metrics:
                if isinstance(metric, AccountsTableCountMetric):
                    metrics.append(contracts.AccountTableCountMetric())
                elif isinstance(metric, AccountsTableAggregateMetric):
                    metrics.append(
                        contracts.AccountTableAggregateMetric(
                            aggregation=contracts.AccountTableAggregation(metric.aggregation.value),
                            definition_id=UUID(metric.column.definitionId),
                            scale=metric.scale,
                        )
                    )
                elif isinstance(metric, AccountsTableCountThresholdMetric):
                    metrics.append(
                        contracts.AccountTableCountThresholdMetric(
                            definition_id=UUID(metric.column.definitionId),
                            operator=contracts.AccountTableThresholdOperator(metric.operator.value),
                            value=metric.value,
                        )
                    )
        except ValueError as error:
            raise ValidationError("Account table metric definition IDs must be valid UUIDs.") from error
        return tuple(metrics)

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
        filters = self._filters()

        try:
            if self.query.metrics is not None:
                metrics_results = api.query_accounts_metrics(
                    team_id=self.team.id,
                    user_access_control=user_access_control,
                    filters=filters,
                    metrics=self._metrics(),
                    include_churned=bool(self.query.includeChurned),
                    include_ignored=bool(self.query.includeIgnored),
                )
                return AccountsTableQueryResponse(
                    results=[],
                    hasMore=False,
                    limit=limit,
                    offset=offset,
                    metricsResults=metrics_results,
                )
            page = api.query_accounts_table(
                team_id=self.team.id,
                user_access_control=user_access_control,
                selection=self._column_selection(),
                filters=filters,
                sort=self._sort(),
                offset=offset,
                limit=limit,
                include_churned=bool(self.query.includeChurned),
                include_ignored=bool(self.query.includeIgnored),
            )
        except api.InvalidAccountTableColumn as error:
            raise ValidationError(str(error)) from error

        return AccountsTableQueryResponse(
            results=[
                AccountsTableRow(
                    id=str(row.id),
                    name=row.name,
                    externalId=row.external_id,
                    logoDomain=row.logo_domain,
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
