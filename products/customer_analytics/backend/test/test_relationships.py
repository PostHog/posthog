from posthog.test.base import BaseTest

from products.customer_analytics.backend.logic import relationships
from products.customer_analytics.backend.models import Account, AccountRelationship, AccountRelationshipDefinition


class TestRelationshipLogic(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = Account.objects.create_account(team=self.team, name="Acme")
        self.other_user = self._create_user("other@posthog.com")

    def _create_definition(self, name="CSM", is_single_holder=True) -> AccountRelationshipDefinition:
        return AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=name, is_single_holder=is_single_holder
        )

    def _get_active_rows_for_account(self, **filters):
        return AccountRelationship.objects.for_team(self.team.id).filter(
            account=self.account, ended_at__isnull=True, **filters
        )

    def test_assign_creates_active_row(self):
        definition = self._create_definition()
        rel = relationships.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=self.user, created_by=self.user
        )
        assert rel.ended_at is None
        assert rel.user == self.user

    def test_reassign_single_holder_closes_previous_and_keeps_history(self):
        definition = self._create_definition()
        first = relationships.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=self.user, created_by=self.user
        )
        second = relationships.assign(
            team_id=self.team.id,
            account=self.account,
            definition=definition,
            user=self.other_user,
            created_by=self.user,
        )
        first.refresh_from_db()
        assert first.ended_at is not None
        assert second.ended_at is None
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).count() == 2

    def test_assign_same_user_is_noop(self):
        definition = self._create_definition()
        first = relationships.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=self.user, created_by=self.user
        )
        second = relationships.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=self.user, created_by=self.user
        )
        assert first.id == second.id

    def test_multi_holder_allows_concurrent_assignees(self):
        definition = self._create_definition(name="FDE", is_single_holder=False)
        relationships.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=self.user, created_by=self.user
        )
        relationships.assign(
            team_id=self.team.id,
            account=self.account,
            definition=definition,
            user=self.other_user,
            created_by=self.user,
        )
        assert self._get_active_rows_for_account(definition=definition).count() == 2

    def test_end_relationship_sets_ended_at(self):
        definition = self._create_definition()
        rel = relationships.assign(
            team_id=self.team.id, account=self.account, definition=definition, user=self.user, created_by=self.user
        )
        ended = relationships.end_relationship(team_id=self.team.id, relationship_id=str(rel.id))
        assert ended.ended_at is not None


class TestSyncFromAccountProperties(BaseTest):
    def setUp(self):
        super().setUp()
        AccountRelationshipDefinition.objects.for_team(self.team.id).create(team_id=self.team.id, name="CSM")
        self.account = Account.objects.create_account(
            team=self.team,
            name="Acme",
            properties={"csm": {"id": self.user.id, "email": self.user.email}, "sfdc_id": "001xx"},
        )

    def _get_active_rows_for_account(self):
        return AccountRelationship.objects.for_team(self.team.id).filter(account=self.account, ended_at__isnull=True)

    def test_sync_creates_rows_from_role_properties(self):
        relationships.sync_from_account_properties(self.account, created_by=self.user)
        rows = self._get_active_rows_for_account()
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.definition.name == "CSM"
        assert row.user_id == self.user.id

    def test_sync_is_idempotent(self):
        relationships.sync_from_account_properties(self.account)
        relationships.sync_from_account_properties(self.account)
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).count() == 1

    def test_sync_ends_relationship_when_key_cleared(self):
        relationships.sync_from_account_properties(self.account)
        Account.objects.update_account(self.account, properties={"sfdc_id": "001xx"})
        relationships.sync_from_account_properties(self.account)
        assert self._get_active_rows_for_account().count() == 0
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).count() == 1

    def test_sync_hands_off_single_holder_on_user_change(self):
        other_user = self._create_user("other@posthog.com")
        relationships.sync_from_account_properties(self.account)
        Account.objects.update_account(
            self.account, properties={"csm": {"id": other_user.id, "email": other_user.email}}
        )
        relationships.sync_from_account_properties(self.account)
        rows = self._get_active_rows_for_account()
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.user_id == other_user.id
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).count() == 2

    def test_sync_skips_unresolvable_users(self):
        Account.objects.update_account(self.account, properties={"csm": {"id": 99999999, "email": "gone@example.com"}})
        relationships.sync_from_account_properties(self.account)
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).count() == 0

    def test_sync_skips_roles_whose_definition_is_missing(self):
        Account.objects.update_account(
            self.account,
            properties={
                "csm": {"id": self.user.id, "email": self.user.email},
                "account_executive": {"id": self.user.id, "email": self.user.email},
            },
        )
        relationships.sync_from_account_properties(self.account)
        rows = self._get_active_rows_for_account()
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.definition.name == "CSM"
