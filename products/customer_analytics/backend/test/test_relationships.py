from datetime import datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.extensions import get_or_create_team_extension

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade import api as facade
from products.customer_analytics.backend.facade.enums import AccountRelationshipSource
from products.customer_analytics.backend.logic import relationships
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipDefinition,
    TeamCustomerAnalyticsConfig,
)
from products.customer_analytics.backend.test.factories import create_account


class TestRelationshipLogic(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.pk, name="Acme")
        self.other_user = self._create_user("other@posthog.com")

    def _create_definition(self, name="CSM", is_single_holder=True) -> AccountRelationshipDefinition:
        return AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name=name, is_single_holder=is_single_holder
        )

    def _get_active_rows_for_account(self, **filters):
        return AccountRelationship.objects.for_team(self.team.id).filter(
            account=self.account, ended_at__isnull=True, **filters
        )

    def _assign(self, definition: AccountRelationshipDefinition, user: User | None = None) -> AccountRelationship:
        return relationships.assign(
            team_id=self.team.id,
            account=self.account,
            definition=definition,
            user=user or self.user,
            actor=relationships.Actor.human(self.user),
        )

    def test_assign_creates_active_row(self):
        definition = self._create_definition()
        rel = self._assign(definition)
        assert rel.ended_at is None
        assert rel.user == self.user

    def test_reassign_single_holder_closes_previous_and_keeps_history(self):
        definition = self._create_definition()
        first = self._assign(definition)
        second = self._assign(definition, self.other_user)
        first.refresh_from_db()
        assert first.ended_at is not None
        assert second.ended_at is None
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).count() == 2

    def test_assign_same_user_is_noop(self):
        definition = self._create_definition()
        first = self._assign(definition)
        second = self._assign(definition)
        assert first.id == second.id

    def test_multi_holder_allows_concurrent_assignees(self):
        definition = self._create_definition(name="FDE", is_single_holder=False)
        self._assign(definition)
        self._assign(definition, self.other_user)
        assert self._get_active_rows_for_account(definition=definition).count() == 2

    def test_end_relationship_sets_ended_at(self):
        definition = self._create_definition()
        rel = self._assign(definition)
        ended = relationships.end_relationship(
            team_id=self.team.id,
            account_id=self.account.id,
            relationship_id=str(rel.id),
            actor=relationships.Actor.human(),
        )
        assert ended.ended_at is not None


class TestBackfillAccountRelationshipsCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(
            team_id=self.team.pk,
            name="Acme",
            _properties={"csm": {"id": self.user.id, "email": self.user.email}, "sfdc_id": "001xx"},
        )

    def _active_rows(self):
        return AccountRelationship.objects.for_team(self.team.id).filter(account=self.account, ended_at__isnull=True)

    def _refreshed_properties(self) -> dict:
        self.account.refresh_from_db()
        return self.account._properties

    def test_backfill_assigns_holders_and_strips_role_keys(self):
        call_command("backfill_account_relationships")
        rows = self._active_rows()
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.definition.name == "CSM"
        assert row.user_id == self.user.id
        assert self._refreshed_properties() == {"sfdc_id": "001xx"}

    def test_backfill_is_idempotent(self):
        call_command("backfill_account_relationships")
        call_command("backfill_account_relationships")
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).count() == 1

    def test_backfill_skips_users_outside_the_organization_but_still_strips(self):
        outsider = User.objects.create_user(email="outsider@example.com", password=None, first_name="Out")
        self.account._properties["csm"] = {"id": outsider.id, "email": outsider.email}
        self.account.save(update_fields=["_properties"])
        call_command("backfill_account_relationships")
        assert self._active_rows().count() == 0
        assert "csm" not in self._refreshed_properties()

    def test_backfill_does_not_overwrite_an_existing_active_holder(self):
        other_user = self._create_user("other@posthog.com")
        definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="CSM"
        )
        relationships.assign(
            team_id=self.team.id,
            account=self.account,
            definition=definition,
            user=other_user,
            actor=relationships.Actor.human(),
        )
        call_command("backfill_account_relationships")
        rows = self._active_rows()
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.user_id == other_user.id
        assert "csm" not in self._refreshed_properties()

    def test_backfill_leaves_a_managed_role_alone(self):
        definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="CSM"
        )
        config = get_or_create_team_extension(self.team, TeamCustomerAnalyticsConfig)
        config.csm_relationship_definition = definition
        config.save(update_fields=["csm_relationship_definition"])
        self.account.csm_ownership_controlled_at = timezone.now()
        self.account.save(update_fields=["csm_ownership_controlled_at"])

        call_command("backfill_account_relationships")

        assert self._active_rows().count() == 0
        assert "csm" not in self._refreshed_properties()

    def test_backfill_dry_run_changes_nothing(self):
        call_command("backfill_account_relationships", "--dry-run")
        assert self._active_rows().count() == 0
        assert "csm" in self._refreshed_properties()


class TestRelationshipFacade(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.pk, name="Acme")

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
            actor=relationships.Actor.human(self.user),
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
            actor=relationships.Actor.human(self.user),
        )
        relationships.end_relationship(
            team_id=self.team.id,
            account_id=self.account.id,
            relationship_id=str(rel.id),
            actor=relationships.Actor.human(),
        )
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
        assert definition.id is not None
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
        assert definition.id is not None
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
        assert definition.id is not None
        other_account = create_account(team_id=self.team.pk, name="Other")
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


class TestExternalRelationshipAssignments(BaseTest):
    def setUp(self):
        super().setUp()
        self.csm_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="CSM"
        )

    def _active_rows(self, account):
        return AccountRelationship.objects.for_team(self.team.id).filter(account=account, ended_at__isnull=True)

    def test_update_external_account_assigns_relationships(self):
        account = create_account(team_id=self.team.pk, name="Acme", external_id="acme-1")
        result = facade.update_external_account(
            self.team.id,
            "acme-1",
            relationship_assignments={str(self.csm_definition.id): self.user.id},
            tags=None,
            tags_mode="add",
        )
        assert result.error is None
        rows = self._active_rows(account)
        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.user_id == self.user.id


class TestCommercialRolePolicy(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.pk, name="Acme")
        self.other_user = self._create_user("other@posthog.com")
        self.ae_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="Account executive"
        )
        self.config = get_or_create_team_extension(self.team, TeamCustomerAnalyticsConfig)
        self.config.ae_relationship_definition = self.ae_definition
        self.config.save(update_fields=["ae_relationship_definition"])
        self.human = relationships.Actor.human(self.user)

    def _manage_ae(self) -> datetime:
        controlled_at = timezone.now() - timedelta(days=1)
        self.account.ae_ownership_controlled_at = controlled_at
        self.account.save(update_fields=["ae_ownership_controlled_at"])
        return controlled_at

    def _fence(self) -> datetime | None:
        return (
            Account.objects.for_team(self.team.id)
            .values_list("ae_ownership_controlled_at", flat=True)
            .get(pk=self.account.pk)
        )

    def _assign(self, user: User, actor: relationships.Actor) -> AccountRelationship:
        return relationships.assign(
            team_id=self.team.id, account=self.account, definition=self.ae_definition, user=user, actor=actor
        )

    def _activity_rows(self) -> list[ActivityLog]:
        return list(ActivityLog.objects.filter(team_id=self.team.id, scope="Account").order_by("created_at"))

    @parameterized.expand(
        [
            (AccountRelationshipSource.WORKFLOW, "assign"),
            (AccountRelationshipSource.AI, "assign"),
            (AccountRelationshipSource.SALESFORCE_CLAIM, "assign"),
            (AccountRelationshipSource.WORKFLOW, "end_active"),
            (AccountRelationshipSource.AI, "end_active"),
        ]
    )
    def test_autonomous_writer_cannot_change_a_managed_role(self, source, operation):
        self._assign(self.other_user, self.human)
        fence = self._manage_ae()
        actor = relationships.Actor(source=source)

        with self.assertRaises(relationships.ManagedRolePolicyError):
            if operation == "assign":
                self._assign(self.user, actor)
            else:
                relationships.end_active(
                    team_id=self.team.id, account=self.account, definition=self.ae_definition, actor=actor
                )

        holder = AccountRelationship.objects.for_team(self.team.id).get(account=self.account, ended_at__isnull=True)
        assert holder.user_id == self.other_user.id
        assert self._fence() == fence

    def test_autonomous_writer_may_fill_an_unmanaged_bound_role_without_taking_authority(self):
        rel = self._assign(
            self.user, relationships.Actor(source=AccountRelationshipSource.WORKFLOW, workflow_id="wf-1")
        )

        assert rel.source == AccountRelationshipSource.WORKFLOW
        assert self._fence() is None
        (row,) = self._activity_rows()
        assert row.activity == "relationship_assigned"
        assert row.is_system is True
        assert row.detail["context"]["source"] == "workflow"
        assert row.detail["context"]["workflow_id"] == "wf-1"
        assert row.detail["context"]["role"] == "ae"

    @parameterized.expand(["assign", "end_active", "confirm_empty", "end_relationship"])
    def test_human_decision_on_a_managed_role_advances_the_fence(self, operation):
        if operation != "confirm_empty":
            rel = self._assign(self.other_user, self.human)
        fence = self._manage_ae()

        if operation == "assign":
            self._assign(self.user, self.human)
        elif operation == "end_active" or operation == "confirm_empty":
            relationships.end_active(
                team_id=self.team.id, account=self.account, definition=self.ae_definition, actor=self.human
            )
        else:
            relationships.end_relationship(
                team_id=self.team.id, account_id=self.account.id, relationship_id=str(rel.id), actor=self.human
            )

        advanced = self._fence()
        assert advanced is not None and advanced > fence
        assert self._activity_rows()[-1].detail["context"]["controlled_at"] == advanced.isoformat()

    def test_confirming_an_empty_managed_role_is_recorded_as_a_decision(self):
        self._manage_ae()

        ended = relationships.end_active(
            team_id=self.team.id, account=self.account, definition=self.ae_definition, actor=self.human
        )

        assert ended == 0
        (row,) = self._activity_rows()
        assert row.activity == "role_confirmed_empty"
        assert row.user_id == self.user.id
        assert row.detail["changes"] == [
            {"type": "Account", "action": "changed", "field": "Account executive", "before": None, "after": None}
        ]

    def test_reassigning_the_current_holder_is_not_a_new_decision(self):
        self._assign(self.user, self.human)
        fence = self._manage_ae()

        self._assign(self.user, self.human)

        assert self._fence() == fence
        assert len(self._activity_rows()) == 1

    def test_activity_write_failure_rolls_back_the_mutation(self):
        fence = self._manage_ae()

        with patch.object(ActivityLog.objects, "bulk_create", side_effect=RuntimeError("audit store down")):
            with self.assertRaises(RuntimeError):
                self._assign(self.user, self.human)

        assert not AccountRelationship.objects.for_team(self.team.id).filter(account=self.account).exists()
        assert self._fence() == fence

    def test_rollback_after_the_audit_row_is_written_leaves_no_row_and_publishes_nothing(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    self._assign(self.user, self.human)
                    raise RuntimeError("a later step in the same transaction failed")

        assert not ActivityLog.objects.filter(team_id=self.team.id, scope="Account").exists()
        assert callbacks == []

    def test_commercial_history_cannot_be_hard_deleted(self):
        rel = self._assign(self.user, self.human)

        with self.assertRaises(relationships.ProtectedRelationshipHistoryError):
            relationships.delete_relationship(
                team_id=self.team.id, account_id=self.account.id, relationship_id=str(rel.id), actor=self.human
            )

        assert AccountRelationship.objects.for_team(self.team.id).filter(id=rel.id).exists()

    def test_bound_definition_cannot_be_deleted_or_made_multi_holder(self):
        with self.assertRaises(facade.AccountRelationshipDefinitionBoundError):
            facade.delete_account_relationship_definition(team_id=self.team.id, definition_id=self.ae_definition.id)
        with self.assertRaises(facade.AccountRelationshipDefinitionBoundError):
            facade.update_account_relationship_definition(
                team_id=self.team.id, definition_id=self.ae_definition.id, fields={"is_single_holder": False}
            )
        assert AccountRelationshipDefinition.objects.for_team(self.team.id).filter(id=self.ae_definition.id).exists()

    def test_managed_account_cannot_be_deleted(self):
        self._manage_ae()

        with self.assertRaises(facade.AccountOwnershipManagedError):
            facade.delete_account_for_view(
                team_id=self.team.id,
                account_id=str(self.account.id),
                user_access_control=UserAccessControl(user=self.user, team=self.team),
                required_level=None,
                organization_id=self.organization.id,
                user=self.user,
                was_impersonated=False,
            )

        assert Account.objects.for_team(self.team.id).filter(id=self.account.id).exists()
