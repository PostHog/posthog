from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest, BaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AccountsTableAccountField,
    AccountsTableAccountFieldColumn,
    AccountsTableCustomPropertyColumn,
    AccountsTableCustomPropertyHistoryColumn,
    AccountsTableNoteCountColumn,
    AccountsTableQuery,
    AccountsTableQueryResponse,
    AccountsTableRelationshipColumn,
    AccountsTableTagsColumn,
)

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Tag, Team
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.customer_analytics.backend.models import (
    AccountRelationship,
    AccountRelationshipDefinition,
    CustomPropertyValue,
    DisplayType,
)
from products.customer_analytics.backend.query_runners.accounts_table_query_runner import AccountsTableQueryRunner
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition
from products.notebooks.backend.models import Notebook, ResourceNotebook

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


class TestAccountsTableQueryRunner(BaseTest):
    def _run(self, query: AccountsTableQuery) -> AccountsTableQueryResponse:
        return AccountsTableQueryRunner(query=query, team=self.team, user=self.user).calculate()

    def test_returns_requested_postgres_cells_with_typed_defaults(self) -> None:
        empty_account = create_account(team_id=self.team.id, name="Empty")
        account = create_account(
            team_id=self.team.id,
            name="Acme",
            external_id="acme-1",
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
                    AccountsTableTagsColumn(),
                    AccountsTableNoteCountColumn(),
                    AccountsTableRelationshipColumn(definitionId=str(relationship_definition.id)),
                    AccountsTableCustomPropertyColumn(definitionId=str(numeric_definition.id)),
                    AccountsTableCustomPropertyColumn(definitionId=str(text_definition.id)),
                    AccountsTableCustomPropertyHistoryColumn(
                        definitionId=str(numeric_definition.id),
                        windowDays=30,
                    ),
                ]
            )
        )

        rows = {row.id: row for row in response.results}
        full_row = rows[str(account.id)]
        assert full_row.accountFields == {"stripe_customer_id": "cus_123"}
        assert full_row.tags == ["enterprise", "priority"]
        assert full_row.noteCount == 1
        assert full_row.relationships == {str(relationship_definition.id): [self.user.id]}
        assert full_row.customProperties == {
            str(numeric_definition.id): 20.0,
            str(text_definition.id): "enterprise",
        }
        assert [point.value for point in full_row.customPropertyHistory[str(numeric_definition.id)]] == [10.0, 20.0]

        empty_row = rows[str(empty_account.id)]
        assert empty_row.tags == []
        assert empty_row.noteCount == 0
        assert empty_row.relationships == {str(relationship_definition.id): []}
        assert empty_row.customProperties == {
            str(numeric_definition.id): None,
            str(text_definition.id): None,
        }
        assert empty_row.customPropertyHistory == {str(numeric_definition.id): []}

    def test_applies_stable_limit_and_offset_pagination(self) -> None:
        accounts = [create_account(team_id=self.team.id, name=name) for name in ["First", "Second", "Third"]]

        response = self._run(AccountsTableQuery(columns=[], limit=1, offset=1))

        assert [row.id for row in response.results] == [str(accounts[1].id)]
        assert response.hasMore is True
        assert response.limit == 1
        assert response.offset == 1

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
            self._run(AccountsTableQuery(columns=[column]))

    def test_rejects_history_for_non_numeric_custom_property(self) -> None:
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")

        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(
                    columns=[AccountsTableCustomPropertyHistoryColumn(definitionId=str(definition.id), windowDays=30)]
                )
            )

    def test_rejects_malformed_definition_id(self) -> None:
        with self.assertRaises(ValidationError):
            self._run(
                AccountsTableQuery(columns=[AccountsTableCustomPropertyColumn(definitionId="not-a-definition-id")])
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
            query=AccountsTableQuery(columns=[]),
            team=self.team,
            user=self.user,
        )
        blocked_cache_key = blocked_runner.get_cache_key()
        response = blocked_runner.calculate()

        assert [row.id for row in response.results] == [str(visible_account.id)]

        blocking_access.delete()
        unblocked_cache_key = AccountsTableQueryRunner(
            query=AccountsTableQuery(columns=[]),
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

    def test_query_endpoint_requires_account_scope_and_dispatches(self) -> None:
        account = create_account(team_id=self.team.id, name="Acme")
        endpoint = f"/api/projects/{self.team.id}/query/"
        payload = {
            "query": AccountsTableQuery(columns=[]).model_dump(),
            "refresh": "force_blocking",
        }

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
