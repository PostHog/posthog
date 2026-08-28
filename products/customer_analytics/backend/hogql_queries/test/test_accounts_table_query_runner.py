from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AccountsTableAccountField,
    AccountsTableAccountFieldColumn,
    AccountsTableAccountFieldFilter,
    AccountsTableAccountFieldOperator,
    AccountsTableAccountIdFilter,
    AccountsTableAggregateMetric,
    AccountsTableAggregation,
    AccountsTableAssignedToFilter,
    AccountsTableCountMetric,
    AccountsTableCountThresholdMetric,
    AccountsTableCustomPropertyColumn,
    AccountsTableCustomPropertyFilter,
    AccountsTableCustomPropertyHistoryColumn,
    AccountsTableCustomPropertyOperator,
    AccountsTableNoteCountColumn,
    AccountsTableQuery,
    AccountsTableQueryResponse,
    AccountsTableRelationshipColumn,
    AccountsTableSearchFilter,
    AccountsTableSort,
    AccountsTableSortDirection,
    AccountsTableTagsColumn,
    AccountsTableTagsFilter,
    AccountsTableThresholdOperator,
    AccountsTableUnassignedFilter,
)

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Tag, Team, User
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.facade import api, contracts
from products.customer_analytics.backend.hogql_queries.accounts_table_query_runner import (
    ACCOUNTS_TABLE_MAX_COLUMNS,
    ACCOUNTS_TABLE_MAX_FILTER_VALUES,
    ACCOUNTS_TABLE_MAX_FILTERS,
    ACCOUNTS_TABLE_MAX_METRICS,
    ACCOUNTS_TABLE_MAX_PAGE_SIZE,
    ACCOUNTS_TABLE_MAX_STRING_LENGTH,
    AccountsTableQueryRunner,
)
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipDefinition,
    CustomPropertyValue,
    DisplayType,
)
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.notebooks.backend.models import Notebook, ResourceNotebook


@freeze_time("2026-01-15T12:00:00Z")
class TestAccountsTableQueryRunner(BaseTest):
    def _run(self, query: AccountsTableQuery) -> AccountsTableQueryResponse:
        return AccountsTableQueryRunner(query=query, team=self.team, user=self.user).calculate()

    def test_returns_requested_postgres_cells_with_typed_defaults(self) -> None:
        empty_account = create_account(team_id=self.team.id, name="Empty")
        account = create_account(
            team_id=self.team.id,
            name="Acme",
            external_id="acme-1",
            churned_at=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
            ignored_at=datetime(2026, 1, 2, 10, 0, tzinfo=UTC),
            _properties={"stripe_customer_id": "cus_123"},
        )

        for tag_name in ["priority", "enterprise"]:
            account.tagged_items.create(tag=Tag.objects.create(team=self.team, name=tag_name))

        notebook = Notebook.objects.create(team=self.team, created_by=self.user)
        ResourceNotebook.objects.create(account=account, notebook=notebook)

        relationship_definition = AccountRelationshipDefinition.objects.unscoped().create(
            team=self.team,
            name="CSM",
        )
        AccountRelationship.objects.unscoped().create(
            team=self.team,
            account=account,
            definition=relationship_definition,
            user=self.user,
        )

        numeric_definition = create_custom_property_definition(
            team_id=self.team.id,
            name="MRR",
            display_type=DisplayType.CURRENCY,
        )
        text_definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        old_value = CustomPropertyValue.objects.unscoped().create(
            team=self.team,
            account=account,
            definition=numeric_definition,
            value_num=10,
            is_deleted=True,
        )
        current_value = CustomPropertyValue.objects.unscoped().create(
            team=self.team,
            account=account,
            definition=numeric_definition,
            value_num=20,
        )
        CustomPropertyValue.objects.unscoped().create(
            team=self.team,
            account=account,
            definition=text_definition,
            value_str="enterprise",
        )
        now = timezone.now()
        CustomPropertyValue.objects.unscoped().filter(id=old_value.id).update(created_at=now - timedelta(days=5))
        CustomPropertyValue.objects.unscoped().filter(id=current_value.id).update(created_at=now - timedelta(days=1))

        response = self._run(
            AccountsTableQuery(
                columns=[
                    AccountsTableAccountFieldColumn(field=AccountsTableAccountField.STRIPE_CUSTOMER_ID),
                    AccountsTableAccountFieldColumn(field=AccountsTableAccountField.CHURNED_AT),
                    AccountsTableAccountFieldColumn(field=AccountsTableAccountField.IGNORED_AT),
                    AccountsTableTagsColumn(),
                    AccountsTableNoteCountColumn(),
                    AccountsTableRelationshipColumn(definitionId=str(relationship_definition.id)),
                    AccountsTableCustomPropertyColumn(definitionId=str(numeric_definition.id)),
                    AccountsTableCustomPropertyColumn(definitionId=str(text_definition.id)),
                    AccountsTableCustomPropertyHistoryColumn(
                        definitionId=str(numeric_definition.id),
                        windowDays=30,
                    ),
                ],
                filters=[],
                includeChurned=True,
                includeIgnored=True,
            )
        )

        rows = {row.id: row for row in response.results}
        full_row = rows[str(account.id)]
        assert full_row.accountFields == {
            "stripe_customer_id": "cus_123",
            "churned_at": "2026-01-01T10:00:00+00:00",
            "ignored_at": "2026-01-02T10:00:00+00:00",
        }
        assert full_row.tags == ["enterprise", "priority"]
        assert full_row.noteCount == 1
        assert full_row.relationships == {str(relationship_definition.id): [self.user.id]}
        assert full_row.customProperties == {
            str(numeric_definition.id): 20.0,
            str(text_definition.id): "enterprise",
        }
        assert [point.value for point in full_row.customPropertyHistory[str(numeric_definition.id)]] == [10.0, 20.0]

        empty_row = rows[str(empty_account.id)]
        assert empty_row.accountFields == {"stripe_customer_id": None, "churned_at": None, "ignored_at": None}
        assert empty_row.tags == []
        assert empty_row.noteCount == 0
        assert empty_row.relationships == {str(relationship_definition.id): []}
        assert empty_row.customProperties == {
            str(numeric_definition.id): None,
            str(text_definition.id): None,
        }
        assert empty_row.customPropertyHistory == {str(numeric_definition.id): []}

    @parameterized.expand(
        [
            ("default", False, ["Active"], 1),
            ("include_churned", True, ["Active", "Churned"], 2),
        ]
    )
    def test_churned_account_visibility(
        self, _name: str, include_churned: bool, expected_names: list[str], expected_count: int
    ) -> None:
        create_account(team_id=self.team.id, name="Active")
        create_account(team_id=self.team.id, name="Churned", churned_at=datetime(2026, 1, 1, tzinfo=UTC))

        rows = self._run(AccountsTableQuery(columns=[], filters=[], includeChurned=include_churned)).results
        metrics = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[],
                metrics=[AccountsTableCountMetric()],
                includeChurned=include_churned,
            )
        ).metricsResults

        assert sorted(row.name for row in rows) == expected_names
        assert metrics == [expected_count]

    @parameterized.expand(
        [
            ("default", False, ["Tracked"], 1),
            ("include_ignored", True, ["Ignored", "Tracked"], 2),
        ]
    )
    def test_ignored_account_visibility(
        self, _name: str, include_ignored: bool, expected_names: list[str], expected_count: int
    ) -> None:
        create_account(team_id=self.team.id, name="Tracked")
        create_account(team_id=self.team.id, name="Ignored", ignored_at=datetime(2026, 1, 1, tzinfo=UTC))

        rows = self._run(AccountsTableQuery(columns=[], filters=[], includeIgnored=include_ignored)).results
        metrics = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[],
                metrics=[AccountsTableCountMetric()],
                includeIgnored=include_ignored,
            )
        ).metricsResults

        assert sorted(row.name for row in rows) == expected_names
        assert metrics == [expected_count]

    def test_calculates_typed_metrics_against_the_filtered_account_set(self) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="MRR",
            display_type=DisplayType.CURRENCY,
        )
        high = create_account(team_id=self.team.id, name="High")
        low = create_account(team_id=self.team.id, name="Low")
        create_account(team_id=self.team.id, name="Unset")
        CustomPropertyValue.objects.unscoped().create(
            team=self.team,
            account=high,
            definition=definition,
            value_num=20,
        )
        CustomPropertyValue.objects.unscoped().create(
            team=self.team,
            account=low,
            definition=definition,
            value_num=5,
        )
        column = AccountsTableCustomPropertyColumn(definitionId=str(definition.id))

        response = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[],
                metrics=[
                    AccountsTableCountMetric(),
                    AccountsTableAggregateMetric(
                        aggregation=AccountsTableAggregation.SUM,
                        column=column,
                        scale=12,
                    ),
                    AccountsTableAggregateMetric(
                        aggregation=AccountsTableAggregation.AVG,
                        column=column,
                    ),
                    AccountsTableAggregateMetric(
                        aggregation=AccountsTableAggregation.MIN,
                        column=column,
                    ),
                    AccountsTableAggregateMetric(
                        aggregation=AccountsTableAggregation.MAX,
                        column=column,
                    ),
                ],
            )
        )
        remaining_response = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[],
                metrics=[
                    AccountsTableAggregateMetric(
                        aggregation=AccountsTableAggregation.MEDIAN,
                        column=column,
                    ),
                    AccountsTableCountThresholdMetric(
                        column=column,
                        operator=AccountsTableThresholdOperator.GT,
                        value=10,
                    ),
                ],
            )
        )

        assert response.results == []
        assert response.metricsResults == [3, 300.0, 12.5, 5.0, 20.0]
        assert remaining_response.results == []
        assert remaining_response.metricsResults == [12.5, 1]

    def test_hydrates_custom_properties_with_bounded_queries(self) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="Health score",
            display_type=DisplayType.NUMBER,
        )
        accounts = [create_account(team_id=self.team.id, name=f"Account {index}") for index in range(3)]
        for index, account in enumerate(accounts):
            CustomPropertyValue.objects.unscoped().create(
                team=self.team,
                account=account,
                definition=definition,
                value_num=index,
            )

        with self.assertNumQueries(7):
            page = api.query_accounts_table(
                team_id=self.team.id,
                user_access_control=UserAccessControl(user=self.user, team=self.team),
                selection=contracts.AccountTableColumnSelection(
                    custom_property_definition_ids=frozenset({definition.id})
                ),
                filters=(),
                sort=None,
                offset=0,
                limit=100,
            )

        assert {row.custom_properties[definition.id] for row in page.rows} == {0.0, 1.0, 2.0}

    def test_resolves_the_logo_domain_from_account_properties(self) -> None:
        from_website_domain = create_account(
            team_id=self.team.id,
            name="From website domain",
            _properties={"website_domain": "acme.example", "email_domains": ["other.example"]},
        )
        from_email_domains = create_account(
            team_id=self.team.id,
            name="From email domains",
            _properties={"email_domains": ["globex.example"]},
        )
        from_external_id = create_account(team_id=self.team.id, name="From external ID", external_id="legacy.example")

        page = api.query_accounts_table(
            team_id=self.team.id,
            user_access_control=UserAccessControl(user=self.user, team=self.team),
            selection=contracts.AccountTableColumnSelection(),
            filters=(),
            sort=None,
            offset=0,
            limit=100,
        )

        logo_domains = {row.id: row.logo_domain for row in page.rows}
        assert logo_domains[from_website_domain.id] == "acme.example"
        assert logo_domains[from_email_domains.id] == "globex.example"
        assert logo_domains[from_external_id.id] is None

    def test_caps_selected_columns_metrics_and_page_size(self) -> None:
        with self.assertRaises(ValidationError):
            self._run(AccountsTableQuery(columns=[AccountsTableTagsColumn()] * (ACCOUNTS_TABLE_MAX_COLUMNS + 1)))

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    metrics=[AccountsTableCountMetric()] * (ACCOUNTS_TABLE_MAX_METRICS + 1),
                )
            )

        response = self._run(AccountsTableQuery(columns=[], limit=ACCOUNTS_TABLE_MAX_PAGE_SIZE + 1))

        assert response.limit == ACCOUNTS_TABLE_MAX_PAGE_SIZE

    @patch.object(api, "ACCOUNT_TABLE_MAX_HISTORY_POINTS", 1)
    def test_rejects_history_results_over_the_point_budget(self) -> None:
        account = create_account(team_id=self.team.id, name="Acme")
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="Health score",
            display_type=DisplayType.NUMBER,
        )
        for index, value in enumerate([10, 20]):
            CustomPropertyValue.objects.unscoped().create(
                team=self.team,
                account=account,
                definition=definition,
                value_num=value,
                is_deleted=index == 0,
            )

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[AccountsTableCustomPropertyHistoryColumn(definitionId=str(definition.id), windowDays=30)]
                )
            )

    def test_applies_stable_limit_and_offset_pagination(self) -> None:
        accounts = [create_account(team_id=self.team.id, name=name) for name in ["First", "Second", "Third"]]

        response = self._run(AccountsTableQuery(columns=[], limit=1, offset=1))
        expected_account = sorted(accounts, key=lambda account: (account.created_at, account.id), reverse=True)[1]

        assert [row.id for row in response.results] == [str(expected_account.id)]
        assert response.hasMore is True
        assert response.limit == 1
        assert response.offset == 1

    def test_combines_search_tag_and_active_assignment_filters(self) -> None:
        active_account = create_account(team_id=self.team.id, name="Acme active")
        ended_account = create_account(team_id=self.team.id, name="Acme ended")
        untagged_account = create_account(team_id=self.team.id, name="Acme untagged")
        tag = Tag.objects.create(team=self.team, name="enterprise")
        active_account.tagged_items.create(tag=tag)
        ended_account.tagged_items.create(tag=tag)
        definition = AccountRelationshipDefinition.objects.unscoped().create(team=self.team, name="CSM")
        AccountRelationship.objects.unscoped().create(
            team=self.team,
            account=active_account,
            definition=definition,
            user=self.user,
        )
        AccountRelationship.objects.unscoped().create(
            team=self.team,
            account=ended_account,
            definition=definition,
            user=self.user,
            ended_at=timezone.now(),
        )

        response = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[
                    AccountsTableSearchFilter(query="acme"),
                    AccountsTableTagsFilter(tagNames=["enterprise"]),
                    AccountsTableAssignedToFilter(userIds=[self.user.id]),
                ],
            )
        )

        assert [row.id for row in response.results] == [str(active_account.id)]
        assert str(untagged_account.id) not in {row.id for row in response.results}

    def test_unassigned_and_account_id_filters(self) -> None:
        assigned_account = create_account(team_id=self.team.id, name="Assigned")
        unassigned_account = create_account(team_id=self.team.id, name="Unassigned")
        definition = AccountRelationshipDefinition.objects.unscoped().create(team=self.team, name="CSM")
        AccountRelationship.objects.unscoped().create(
            team=self.team,
            account=assigned_account,
            definition=definition,
            user=self.user,
        )

        unassigned_response = self._run(AccountsTableQuery(columns=[], filters=[AccountsTableUnassignedFilter()]))
        account_response = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[AccountsTableAccountIdFilter(accountId=str(assigned_account.id))],
            )
        )

        assert [row.id for row in unassigned_response.results] == [str(unassigned_account.id)]
        assert [row.id for row in account_response.results] == [str(assigned_account.id)]

    @parameterized.expand(
        [
            (
                "name_contains",
                AccountsTableAccountField.NAME,
                AccountsTableAccountFieldOperator.ICONTAINS,
                ["ter"],
                {"Enterprise"},
            ),
            (
                "connection_id_exact",
                AccountsTableAccountField.STRIPE_CUSTOMER_ID,
                AccountsTableAccountFieldOperator.EXACT,
                ["cus_123"],
                {"Enterprise"},
            ),
            (
                "negative_includes_unset",
                AccountsTableAccountField.STRIPE_CUSTOMER_ID,
                AccountsTableAccountFieldOperator.IS_NOT,
                ["cus_123"],
                {"Basic"},
            ),
            (
                "created_exact",
                AccountsTableAccountField.CREATED_AT,
                AccountsTableAccountFieldOperator.IS_DATE_EXACT,
                ["2026-01-01"],
                {"Enterprise"},
            ),
            (
                "created_before",
                AccountsTableAccountField.CREATED_AT,
                AccountsTableAccountFieldOperator.IS_DATE_BEFORE,
                ["2026-01-15"],
                {"Enterprise"},
            ),
            (
                "created_after",
                AccountsTableAccountField.CREATED_AT,
                AccountsTableAccountFieldOperator.IS_DATE_AFTER,
                ["2026-01-15"],
                {"Basic"},
            ),
            (
                "ignored_is_set",
                AccountsTableAccountField.IGNORED_AT,
                AccountsTableAccountFieldOperator.IS_SET,
                [],
                {"Enterprise"},
            ),
            (
                "ignored_is_not_set",
                AccountsTableAccountField.IGNORED_AT,
                AccountsTableAccountFieldOperator.IS_NOT_SET,
                [],
                {"Basic"},
            ),
        ]
    )
    def test_filters_native_account_fields(
        self,
        _name: str,
        field: AccountsTableAccountField,
        operator: AccountsTableAccountFieldOperator,
        values: list[str],
        expected_names: set[str],
    ) -> None:
        enterprise = create_account(
            team_id=self.team.id,
            name="Enterprise",
            ignored_at=(datetime(2026, 1, 5, tzinfo=UTC) if field == AccountsTableAccountField.IGNORED_AT else None),
            _properties={"stripe_customer_id": "cus_123"},
        )
        basic = create_account(team_id=self.team.id, name="Basic")
        Account.objects.unscoped().filter(id=enterprise.id).update(created_at=datetime(2026, 1, 1, tzinfo=UTC))
        Account.objects.unscoped().filter(id=basic.id).update(created_at=datetime(2026, 2, 1, tzinfo=UTC))

        response = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[AccountsTableAccountFieldFilter(field=field, operator=operator, values=values)],
            )
        )

        assert {row.name for row in response.results} == expected_names

    @parameterized.expand(
        [
            (
                "ignored",
                [
                    AccountsTableAccountFieldFilter(
                        field=AccountsTableAccountField.IGNORED_AT,
                        operator=AccountsTableAccountFieldOperator.IS_SET,
                    )
                ],
                {"Active ignored"},
            ),
            (
                "churned",
                [
                    AccountsTableAccountFieldFilter(
                        field=AccountsTableAccountField.CHURNED_AT,
                        operator=AccountsTableAccountFieldOperator.IS_SET,
                    )
                ],
                {"Churned tracked"},
            ),
            (
                "churned_and_ignored",
                [
                    AccountsTableAccountFieldFilter(
                        field=AccountsTableAccountField.CHURNED_AT,
                        operator=AccountsTableAccountFieldOperator.IS_SET,
                    ),
                    AccountsTableAccountFieldFilter(
                        field=AccountsTableAccountField.IGNORED_AT,
                        operator=AccountsTableAccountFieldOperator.IS_SET,
                    ),
                ],
                {"Churned ignored"},
            ),
        ]
    )
    def test_lifecycle_filters_include_the_requested_state_for_rows_and_metrics(
        self,
        _name: str,
        filters: list[AccountsTableAccountFieldFilter],
        expected_names: set[str],
    ) -> None:
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        create_account(team_id=self.team.id, name="Active tracked")
        create_account(team_id=self.team.id, name="Active ignored", ignored_at=timestamp)
        create_account(team_id=self.team.id, name="Churned tracked", churned_at=timestamp)
        create_account(team_id=self.team.id, name="Churned ignored", churned_at=timestamp, ignored_at=timestamp)

        rows = self._run(AccountsTableQuery(columns=[], filters=filters)).results
        metrics = self._run(
            AccountsTableQuery(columns=[], filters=filters, metrics=[AccountsTableCountMetric()])
        ).metricsResults

        assert {row.name for row in rows} == expected_names
        assert metrics == [len(expected_names)]

    @parameterized.expand(
        [
            (
                "date_on_text",
                AccountsTableAccountField.NAME,
                AccountsTableAccountFieldOperator.IS_DATE_AFTER,
                ["2026-01-01"],
            ),
            (
                "contains_on_date",
                AccountsTableAccountField.CREATED_AT,
                AccountsTableAccountFieldOperator.ICONTAINS,
                ["2026"],
            ),
        ]
    )
    def test_rejects_account_field_operator_for_wrong_type(
        self,
        _name: str,
        field: AccountsTableAccountField,
        operator: AccountsTableAccountFieldOperator,
        values: list[str],
    ) -> None:
        create_account(team_id=self.team.id, name="Account")

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    filters=[AccountsTableAccountFieldFilter(field=field, operator=operator, values=values)],
                )
            )

    @parameterized.expand(
        [
            ("greater_than", AccountsTableCustomPropertyOperator.GT, [10], {"High"}),
            ("negative_includes_unset", AccountsTableCustomPropertyOperator.IS_NOT, [20], {"Low", "Unset"}),
            ("is_not_set", AccountsTableCustomPropertyOperator.IS_NOT_SET, [], {"Unset"}),
        ]
    )
    def test_filters_typed_custom_properties(
        self,
        _name: str,
        operator: AccountsTableCustomPropertyOperator,
        values: list[int],
        expected_names: set[str],
    ) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="MRR",
            display_type=DisplayType.CURRENCY,
        )
        high = create_account(team_id=self.team.id, name="High")
        low = create_account(team_id=self.team.id, name="Low")
        create_account(team_id=self.team.id, name="Unset")
        CustomPropertyValue.objects.unscoped().create(team=self.team, account=high, definition=definition, value_num=20)
        CustomPropertyValue.objects.unscoped().create(team=self.team, account=low, definition=definition, value_num=5)

        response = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[
                    AccountsTableCustomPropertyFilter(
                        definitionId=str(definition.id),
                        operator=operator,
                        values=values,
                    )
                ],
            )
        )

        assert {row.name for row in response.results} == expected_names

    @parameterized.expand(
        [
            (
                "text_contains",
                DisplayType.TEXT,
                {"value_str": "enterprise"},
                AccountsTableCustomPropertyOperator.ICONTAINS,
                ["ter"],
                {"Set"},
            ),
            (
                "negative_text_includes_unset",
                DisplayType.TEXT,
                {"value_str": "enterprise"},
                AccountsTableCustomPropertyOperator.NOT_ICONTAINS,
                ["zzz"],
                {"Set", "Unset"},
            ),
            (
                "boolean",
                DisplayType.BOOLEAN,
                {"value_bool": True},
                AccountsTableCustomPropertyOperator.EXACT,
                ["true"],
                {"Set"},
            ),
            (
                "date",
                DisplayType.DATE,
                {"value_datetime": datetime(2026, 1, 1, 14, 30, tzinfo=UTC)},
                AccountsTableCustomPropertyOperator.IS_DATE_BEFORE,
                ["2026-02-01T00:00:00Z"],
                {"Set"},
            ),
        ]
    )
    def test_filters_custom_property_operator_families(
        self,
        _name: str,
        display_type: DisplayType,
        value_kwargs: dict[str, object],
        operator: AccountsTableCustomPropertyOperator,
        values: list[str],
        expected_names: set[str],
    ) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name=f"Property {_name}",
            display_type=display_type,
        )
        set_account = create_account(team_id=self.team.id, name="Set")
        create_account(team_id=self.team.id, name="Unset")
        CustomPropertyValue.objects.unscoped().create(
            team=self.team,
            account=set_account,
            definition=definition,
            **value_kwargs,
        )

        response = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[
                    AccountsTableCustomPropertyFilter(
                        definitionId=str(definition.id),
                        operator=operator,
                        values=values,
                    )
                ],
            )
        )

        assert {row.name for row in response.results} == expected_names

    def test_rejects_excessive_filter_count_and_string_length(self) -> None:
        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    filters=[AccountsTableSearchFilter(query="a")] * (ACCOUNTS_TABLE_MAX_FILTERS + 1),
                )
            )

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    filters=[AccountsTableSearchFilter(query="a" * (ACCOUNTS_TABLE_MAX_STRING_LENGTH + 1))],
                )
            )

    def test_rejects_excessive_custom_property_filter_values(self) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id,
            name="Health score",
            display_type=DisplayType.NUMBER,
        )

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    filters=[
                        AccountsTableCustomPropertyFilter(
                            definitionId=str(definition.id),
                            operator=AccountsTableCustomPropertyOperator.EXACT,
                            values=list(range(ACCOUNTS_TABLE_MAX_FILTER_VALUES + 1)),
                        )
                    ],
                )
            )

    def test_sorts_before_paginating_across_supported_column_kinds(self) -> None:
        alpha = create_account(team_id=self.team.id, name="Alpha", _properties={"stripe_customer_id": "cus_z"})
        beta = create_account(team_id=self.team.id, name="Beta", _properties={"stripe_customer_id": "cus_a"})
        create_account(team_id=self.team.id, name="Gamma")
        alpha.tagged_items.create(tag=Tag.objects.create(team=self.team, name="z-tag"))
        beta.tagged_items.create(tag=Tag.objects.create(team=self.team, name="a-tag"))
        for account, count in [(alpha, 2), (beta, 1)]:
            for _ in range(count):
                ResourceNotebook.objects.create(
                    account=account,
                    notebook=Notebook.objects.create(team=self.team, created_by=self.user),
                )
        relationship_definition = AccountRelationshipDefinition.objects.unscoped().create(team=self.team, name="CSM")
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        AccountRelationship.objects.unscoped().create(
            team=self.team, account=alpha, definition=relationship_definition, user=self.user
        )
        AccountRelationship.objects.unscoped().create(
            team=self.team, account=beta, definition=relationship_definition, user=other_user
        )
        custom_property_definition = create_custom_property_definition(
            team_id=self.team.id, name="MRR", display_type=DisplayType.CURRENCY
        )
        CustomPropertyValue.objects.unscoped().create(
            team=self.team, account=alpha, definition=custom_property_definition, value_num=20
        )
        CustomPropertyValue.objects.unscoped().create(
            team=self.team, account=beta, definition=custom_property_definition, value_num=5
        )

        paginated = self._run(
            AccountsTableQuery(
                columns=[],
                filters=[],
                sort=AccountsTableSort(
                    column=AccountsTableAccountFieldColumn(field=AccountsTableAccountField.NAME),
                    direction=AccountsTableSortDirection.ASC,
                ),
                limit=1,
                offset=1,
            )
        )
        assert [row.name for row in paginated.results] == ["Beta"]
        assert paginated.hasMore is True

        sort_cases = [
            (
                AccountsTableAccountFieldColumn(field=AccountsTableAccountField.STRIPE_CUSTOMER_ID),
                ["Beta", "Alpha", "Gamma"],
            ),
            (AccountsTableTagsColumn(), ["Beta", "Alpha", "Gamma"]),
            (AccountsTableNoteCountColumn(), ["Alpha", "Beta", "Gamma"]),
            (
                AccountsTableRelationshipColumn(definitionId=str(relationship_definition.id)),
                ["Alpha", "Beta", "Gamma"],
            ),
            (
                AccountsTableCustomPropertyColumn(definitionId=str(custom_property_definition.id)),
                ["Beta", "Alpha", "Gamma"],
            ),
        ]
        for column, expected_names in sort_cases:
            with self.subTest(column_type=type(column).__name__):
                direction = (
                    AccountsTableSortDirection.DESC
                    if isinstance(column, AccountsTableNoteCountColumn)
                    else AccountsTableSortDirection.ASC
                )
                response = self._run(
                    AccountsTableQuery(
                        columns=[],
                        filters=[],
                        sort=AccountsTableSort(column=column, direction=direction),
                    )
                )
                assert [row.name for row in response.results] == expected_names

    def test_rejects_regex_custom_property_filters(self) -> None:
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    filters=[
                        AccountsTableCustomPropertyFilter(
                            definitionId=str(definition.id),
                            operator=AccountsTableCustomPropertyOperator.REGEX,
                            values=["^enter.*"],
                        )
                    ],
                )
            )

    def test_rejects_operator_incompatible_with_custom_property_type(self) -> None:
        definition = create_custom_property_definition(
            team_id=self.team.id, name="MRR", display_type=DisplayType.CURRENCY
        )

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    filters=[
                        AccountsTableCustomPropertyFilter(
                            definitionId=str(definition.id),
                            operator=AccountsTableCustomPropertyOperator.ICONTAINS,
                            values=["2"],
                        )
                    ],
                )
            )

    @parameterized.expand(["relationship", "custom_property"])
    def test_rejects_definition_from_another_team(self, column_kind: str) -> None:
        other_team = Team.objects.create(organization=self.organization)
        column: AccountsTableRelationshipColumn | AccountsTableCustomPropertyColumn
        if column_kind == "relationship":
            relationship_definition = AccountRelationshipDefinition.objects.unscoped().create(
                team=other_team, name="Other CSM"
            )
            column = AccountsTableRelationshipColumn(definitionId=str(relationship_definition.id))
        else:
            custom_property_definition = create_custom_property_definition(team_id=other_team.id, name="Other plan")
            column = AccountsTableCustomPropertyColumn(definitionId=str(custom_property_definition.id))

        with self.assertRaises(ValidationError):
            self._run(AccountsTableQuery(columns=[column], filters=[]))

    @parameterized.expand(["filter", "sort"])
    def test_rejects_filter_or_sort_definition_from_another_team(self, query_part: str) -> None:
        other_team = Team.objects.create(organization=self.organization)
        definition = create_custom_property_definition(team_id=other_team.id, name="Other plan")
        filter_ = (
            AccountsTableCustomPropertyFilter(
                definitionId=str(definition.id),
                operator=AccountsTableCustomPropertyOperator.IS_SET,
                values=[],
            )
            if query_part == "filter"
            else None
        )
        sort = (
            AccountsTableSort(
                column=AccountsTableCustomPropertyColumn(definitionId=str(definition.id)),
                direction=AccountsTableSortDirection.ASC,
            )
            if query_part == "sort"
            else None
        )

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[],
                    filters=[filter_] if filter_ else [],
                    sort=sort,
                )
            )

    def test_rejects_history_for_non_numeric_custom_property(self) -> None:
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[AccountsTableCustomPropertyHistoryColumn(definitionId=str(definition.id), windowDays=30)],
                    filters=[],
                )
            )

    def test_rejects_malformed_definition_id(self) -> None:
        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[AccountsTableCustomPropertyColumn(definitionId="not-a-definition-id")],
                    filters=[],
                )
            )

    @pytest.mark.ee
    def test_object_access_filters_rows_and_partitions_the_cache(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        visible_account = create_account(team_id=self.team.id, name="Visible")
        denied_account = create_account(team_id=self.team.id, name="Denied")
        blocking_access = AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(denied_account.id),
            access_level="none",
            organization_member=self.organization_membership,
        )

        blocked_runner = AccountsTableQueryRunner(
            query=AccountsTableQuery(columns=[], filters=[], limit=1),
            team=self.team,
            user=self.user,
        )
        blocked_cache_key = blocked_runner.get_cache_key()
        response = blocked_runner.calculate()

        assert [row.id for row in response.results] == [str(visible_account.id)]

        blocking_access.delete()
        unblocked_cache_key = AccountsTableQueryRunner(
            query=AccountsTableQuery(columns=[], filters=[], limit=1),
            team=self.team,
            user=self.user,
        ).get_cache_key()
        assert blocked_cache_key != unblocked_cache_key


class TestAccountsTableQueryAPI(APIBaseTest):
    def _token(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="accounts table query",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
            scoped_teams=[],
            scoped_organizations=[],
        )
        return value

    def test_query_endpoint_rejects_unsupported_filters(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/query/",
            {
                "query": {
                    "kind": "AccountsTableQuery",
                    "columns": [],
                    "filters": [{"kind": "unsupported"}],
                },
                "refresh": "force_blocking",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_query_endpoint_requires_account_scope_and_dispatches(self) -> None:
        account = create_account(team_id=self.team.id, name="Acme")
        endpoint = f"/api/projects/{self.team.id}/query/"
        accounts_query = AccountsTableQuery(columns=[], filters=[]).model_dump()

        for query in [accounts_query, {"kind": "DataTableNode", "source": accounts_query}]:
            with self.subTest(query_kind=query["kind"]):
                payload = {"query": query, "refresh": "force_blocking"}
                for incomplete_scopes in [["query:read"], ["account:read"]]:
                    denied = self.client.post(
                        endpoint,
                        payload,
                        format="json",
                        headers={"authorization": f"Bearer {self._token(incomplete_scopes)}"},
                    )
                    assert denied.status_code == status.HTTP_403_FORBIDDEN

                allowed = self.client.post(
                    endpoint,
                    payload,
                    format="json",
                    headers={"authorization": f"Bearer {self._token(['query:read', 'account:read'])}"},
                )
                assert allowed.status_code == status.HTTP_200_OK, allowed.content
                assert [row["id"] for row in allowed.json()["results"]] == [str(account.id)]
