from posthog.test.base import BaseTest

from posthog.models import Team, User

from products.customer_analytics.backend.facade import api as facade
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
        ended = relationships.end_relationship(
            team_id=self.team.id, account_id=self.account.id, relationship_id=str(rel.id)
        )
        assert ended.ended_at is not None


class TestRelationshipFacade(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = Account.objects.create_account(team=self.team, name="Acme")

    def test_create_and_list_definitions_roundtrip(self):
        created = facade.create_account_relationship_definition(
            team_id=self.team.id, name="Onboarding manager", description="Runs onboarding", created_by=self.user
        )
        listed, total = facade.list_account_relationship_definitions(self.team.id)
        assert total == 1
        assert [d.id for d in listed] == [created.id]
        assert listed[0].description == "Runs onboarding"
        assert listed[0].is_single_holder is True

    def test_update_definition_renames_and_toggles_cardinality(self):
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="FDE", created_by=self.user
        )
        assert definition.id is not None
        updated = facade.update_account_relationship_definition(
            team_id=self.team.id,
            definition_id=definition.id,
            fields={"name": "Field engineer", "is_single_holder": False},
        )
        assert updated is not None
        assert updated.name == "Field engineer"
        assert updated.is_single_holder is False

    def test_update_definition_name_collision_raises_conflict(self):
        facade.create_account_relationship_definition(team_id=self.team.id, name="CSM", created_by=self.user)
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="FDE", created_by=self.user
        )
        assert definition.id is not None
        with self.assertRaises(facade.AccountRelationshipDefinitionConflictError):
            facade.update_account_relationship_definition(
                team_id=self.team.id, definition_id=definition.id, fields={"name": "CSM"}
            )

    def test_update_definition_unknown_id_returns_none(self):
        assert (
            facade.update_account_relationship_definition(
                team_id=self.team.id, definition_id="00000000-0000-0000-0000-000000000000", fields={"name": "X"}
            )
            is None
        )

    def test_create_duplicate_definition_name_raises_conflict(self):
        facade.create_account_relationship_definition(team_id=self.team.id, name="CSM", created_by=self.user)
        with self.assertRaises(facade.AccountRelationshipDefinitionConflictError):
            facade.create_account_relationship_definition(team_id=self.team.id, name="CSM", created_by=self.user)

    def test_delete_definition_cascades_history(self):
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="CSM", created_by=self.user
        )
        assert definition.id is not None
        model_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).get(id=definition.id)
        relationships.assign(
            team_id=self.team.id,
            account=self.account,
            definition=model_definition,
            user=self.user,
            created_by=self.user,
        )
        assert facade.delete_account_relationship_definition(team_id=self.team.id, definition_id=definition.id)
        assert AccountRelationship.objects.for_team(self.team.id).count() == 0

    def test_list_relationships_current_vs_history(self):
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="CSM", created_by=self.user
        )
        assert definition.id is not None
        model_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).get(id=definition.id)
        rel = relationships.assign(
            team_id=self.team.id,
            account=self.account,
            definition=model_definition,
            user=self.user,
            created_by=self.user,
        )
        relationships.end_relationship(team_id=self.team.id, account_id=self.account.id, relationship_id=str(rel.id))
        assert facade.list_account_relationships(team_id=self.team.id, account_id=self.account.id) == []
        history = facade.list_account_relationships(
            team_id=self.team.id, account_id=self.account.id, include_history=True
        )
        assert len(history) == 1
        assert history[0].ended_at is not None
        assert history[0].user is not None
        assert history[0].user.email == self.user.email

    def test_assign_and_end_roundtrip(self):
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="CSM", created_by=self.user
        )
        assigned = facade.assign_account_relationship(
            team_id=self.team.id,
            account_id=self.account.id,
            definition_id=definition.id,
            user_id=self.user.id,
            created_by=self.user,
        )
        assert assigned.ended_at is None
        assert assigned.user is not None
        assert assigned.user.email == self.user.email
        ended = facade.end_account_relationship(
            team_id=self.team.id, account_id=self.account.id, relationship_id=assigned.id
        )
        assert ended is not None
        assert ended.ended_at is not None
        assert (
            facade.end_account_relationship(
                team_id=self.team.id, account_id=self.account.id, relationship_id=assigned.id
            )
            is None
        )

    def test_assign_validates_definition_and_assignee(self):
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="CSM", created_by=self.user
        )
        outsider = User.objects.create_user("outsider@example.com", None, "")
        with self.assertRaises(facade.AccountRelationshipDefinitionNotFound):
            facade.assign_account_relationship(
                team_id=self.team.id,
                account_id=self.account.id,
                definition_id="00000000-0000-0000-0000-000000000000",
                user_id=self.user.id,
                created_by=self.user,
            )
        with self.assertRaises(facade.AccountRelationshipAssigneeNotInOrganization):
            facade.assign_account_relationship(
                team_id=self.team.id,
                account_id=self.account.id,
                definition_id=definition.id,
                user_id=outsider.id,
                created_by=self.user,
            )

    def test_end_is_scoped_to_the_account(self):
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="CSM", created_by=self.user
        )
        other_account = Account.objects.create_account(team=self.team, name="Other")
        assigned = facade.assign_account_relationship(
            team_id=self.team.id,
            account_id=self.account.id,
            definition_id=definition.id,
            user_id=self.user.id,
            created_by=self.user,
        )
        assert (
            facade.end_account_relationship(
                team_id=self.team.id, account_id=other_account.id, relationship_id=assigned.id
            )
            is None
        )

    def test_team_isolation(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        definition = facade.create_account_relationship_definition(
            team_id=self.team.id, name="CSM", created_by=self.user
        )
        assert definition.id is not None
        assert facade.list_account_relationship_definitions(other_team.id) == ([], 0)
        assert facade.list_account_relationships(team_id=other_team.id, account_id=self.account.id) == []
        assert not facade.delete_account_relationship_definition(team_id=other_team.id, definition_id=definition.id)
