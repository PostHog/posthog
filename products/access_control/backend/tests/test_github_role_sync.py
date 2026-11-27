from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.integrations import IntegrationManager
from posthog.models import OrganizationMembership, User
from posthog.models.integration import GitHubIntegration

from products.access_control.backend.facade.api import (
    apply_role_external_reference_sync,
    compute_role_reference_drifts,
    likely_role,
    sync_organization_github_roles,
    sync_single_github_team_webhook,
)
from products.access_control.backend.facade.contracts import RoleMatchSource, RoleSyncActionMode, RoleSyncMode
from products.access_control.backend.github_role_sync import (
    ExistingReferenceRecord,
    ExistingRoleRecord,
    GitHubTeamSnapshot,
    compute_role_membership_drift,
    plan_github_org_role_sync,
)
from products.access_control.backend.models.role import Role, RoleMembership
from products.access_control.backend.models.role_external_reference import RoleExternalReference


class TestGitHubRoleSyncPure(SimpleTestCase):
    def test_plans_role_creation_proposal_auto_update_and_orphan_slug_release(self) -> None:
        security_role_id = uuid4()
        synced_role_id = uuid4()
        orphan_role_id = uuid4()
        synced_ref_id = uuid4()
        orphan_ref_id = uuid4()
        now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)

        existing_roles = [
            ExistingRoleRecord(id=security_role_id, name="Security", member_user_ids=frozenset({1})),
            ExistingRoleRecord(id=synced_role_id, name="Old Cymbal", member_user_ids=frozenset({2})),
            ExistingRoleRecord(id=orphan_role_id, name="Legacy Platform", member_user_ids=frozenset({3})),
        ]
        existing_references = [
            ExistingReferenceRecord(
                id=synced_ref_id,
                provider_organization_id="posthog",
                provider_role_id="1001",
                provider_role_slug="team-cymbal",
                provider_role_name="Old Cymbal",
                role_id=synced_role_id,
                role_name="Old Cymbal",
                sync_mode=RoleSyncMode.AUTO,
                role_created_by_sync=True,
                provider_member_logins=("bob",),
                orphaned_at=None,
                last_synced_at=now,
            ),
            ExistingReferenceRecord(
                id=orphan_ref_id,
                provider_organization_id="posthog",
                provider_role_id="1002",
                provider_role_slug="team-platform",
                provider_role_name="Legacy Platform",
                role_id=orphan_role_id,
                role_name="Legacy Platform",
                sync_mode=RoleSyncMode.AUTO,
                role_created_by_sync=True,
                provider_member_logins=("carol",),
                orphaned_at=None,
                last_synced_at=now,
            ),
        ]
        github_teams = [
            # Renamed team #1001 updates existing AUTO reference + renames Role + updates members
            GitHubTeamSnapshot(
                provider_role_id="1001",
                slug="team-error-tracking",
                name="Error Tracking",
                member_logins=("alice", "bob"),
            ),
            # Matches pre-existing manual "Security" role -> PROPOSED without touching members
            GitHubTeamSnapshot(
                provider_role_id="2001",
                slug="team-security",
                name="Team Security",
                member_logins=("alice", "carol"),
            ),
            # Brand-new team #3001 reuses orphaned team #1002's slug "team-platform"
            GitHubTeamSnapshot(
                provider_role_id="3001",
                slug="team-platform",
                name="Platform",
                member_logins=("carol",),
            ),
        ]

        plan = plan_github_org_role_sync(
            github_organization="PostHog",
            github_teams=github_teams,
            existing_roles=existing_roles,
            existing_references=existing_references,
            login_to_user_id={"alice": 1, "bob": 2, "carol": 3},
            complete_org_team_list=True,
        )

        assert len(plan.update_references) == 1
        update_op = plan.update_references[0]
        assert update_op.reference_id == synced_ref_id
        assert update_op.provider_role_slug == "team-error-tracking"
        assert update_op.rename_role_to == "Error Tracking"
        assert update_op.reconcile_members is True
        assert update_op.desired_user_ids == frozenset({1, 2})

        assert len(plan.create_proposals) == 1
        proposal = plan.create_proposals[0]
        assert proposal.role_id == security_role_id
        assert proposal.provider_role_slug == "team-security"

        assert len(plan.create_roles) == 1
        creation = plan.create_roles[0]
        assert creation.role_name == "Platform"
        assert creation.provider_role_id == "3001"
        assert creation.provider_role_slug == "team-platform"
        assert creation.member_user_ids == frozenset({3})

        assert len(plan.orphan_references) == 1
        orphan_op = plan.orphan_references[0]
        assert orphan_op.reference_id == orphan_ref_id
        assert orphan_op.mark_orphaned is True
        assert orphan_op.clear_slug is True

    @parameterized.expand(
        [
            ("unsynced", frozenset({1}), None, False, frozenset(), frozenset(), None),
            ("in_sync", frozenset({1, 2}), ("alice", "bob", "external"), False, frozenset(), frozenset(), 3),
            ("drift_both_ways", frozenset({1, 3}), ("alice", "bob"), True, frozenset({2}), frozenset({3}), 2),
        ]
    )
    def test_compute_role_membership_drift(
        self,
        _name: str,
        current_ids: frozenset[int],
        provider_logins: tuple[str, ...] | None,
        expected_drift: bool,
        expected_add: frozenset[int],
        expected_remove: frozenset[int],
        expected_provider_count: int | None,
    ) -> None:
        drift = compute_role_membership_drift(
            current_user_ids=current_ids,
            provider_member_logins=provider_logins,
            login_to_user_id={"alice": 1, "bob": 2, "carol": 3},
        )
        assert drift.has_drift is expected_drift
        assert drift.to_add_user_ids == expected_add
        assert drift.to_remove_user_ids == expected_remove
        assert drift.provider_member_count == expected_provider_count


class TestGitHubRoleSyncService(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.alice = self.user
        UserSocialAuth.objects.create(
            user=self.alice,
            provider="github",
            uid="gh-1",
            extra_data={"login": "AliceGH"},
        )
        self.bob = User.objects.create(email="bob@example.com", first_name="Bob")
        self.bob_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.bob,
        )
        UserSocialAuth.objects.create(
            user=self.bob,
            provider="github",
            uid="gh-2",
            extra_data={"login": "bobgh"},
        )

        self.integration = IntegrationManager.github.oauth.create(
            self.team.id,
            external_id="998877",
            config={
                "account": {"name": "PostHog", "type": "Organization"},
                "installation_id": 998877,
                "permissions": {"members": "read", "contents": "write"},
            },
            created_by_id=self.alice.id,
        )

    def test_ingests_new_roles_proposes_manual_roles_handles_renames_and_orphans(self) -> None:
        # Pre-existing manual PostHog role with only Alice: must NOT be auto-mutated!
        manual_security = Role.objects.create(name="Security", organization=self.organization)
        RoleMembership.objects.create(
            role=manual_security,
            user=self.alice,
            organization_member=self.organization_membership,
        )

        def fake_members(_org: str, slug: str) -> dict:
            if slug == "team-security":
                return {"success": True, "logins": ["alicegh", "bobgh"]}
            if slug == "team-new-growth":
                return {"success": True, "logins": ["bobgh"]}
            return {"success": True, "logins": []}

        with (
            patch.object(
                GitHubIntegration,
                "list_teams",
                return_value=(
                    [
                        {"id": 501, "slug": "team-security", "name": "Team Security"},
                        {"id": 502, "slug": "team-new-growth", "name": "New Growth"},
                    ],
                    False,
                ),
            ),
            patch.object(GitHubIntegration, "list_team_members", side_effect=fake_members),
        ):
            outcome = sync_organization_github_roles(organization_id=self.organization.id, interactive=True)

        assert outcome.created_roles == 1
        assert outcome.proposed_roles == 1
        assert outcome.skipped_missing_members_permission is False

        # 1) Newly created GitHub role is immediately resolvable via likely_role and has Bob synced
        matched_growth = likely_role("@posthog/team-new-growth", team_id=self.team.id)
        assert matched_growth is not None
        assert matched_growth.name == "New Growth"
        assert matched_growth.source == RoleMatchSource.EXTERNAL_REFERENCE
        growth_member_ids = set(
            RoleMembership.objects.filter(role_id=matched_growth.id).values_list("user_id", flat=True)
        )
        assert growth_member_ids == {self.bob.id}

        # 2) Pre-existing manual Security role stayed untouched (Alice only) and records drift (+Bob)
        security_ref = RoleExternalReference.objects.get(role=manual_security)
        assert security_ref.sync_mode == RoleExternalReference.SyncMode.PROPOSED
        assert security_ref.role_created_by_sync is False
        assert set(RoleMembership.objects.filter(role=manual_security).values_list("user_id", flat=True)) == {
            self.alice.id
        }
        drifts = compute_role_reference_drifts(
            organization_id=self.organization.id,
            reference_ids=[security_ref.id],
        )
        assert drifts[security_ref.id].has_drift is True
        assert drifts[security_ref.id].to_add_user_ids == frozenset({self.bob.id})

        # 3) Admin clicks "Sync once" -> Bob is added, mode becomes MANUAL
        apply_role_external_reference_sync(
            organization_id=self.organization.id,
            reference_id=security_ref.id,
            mode=RoleSyncActionMode.ONCE,
        )
        security_ref.refresh_from_db()
        assert security_ref.sync_mode == RoleExternalReference.SyncMode.MANUAL
        assert set(RoleMembership.objects.filter(role=manual_security).values_list("user_id", flat=True)) == {
            self.alice.id,
            self.bob.id,
        }

        # 4) Webhook renames team 502 on GitHub + adds Alice, and deletes team 501
        with patch.object(
            GitHubIntegration,
            "list_team_members",
            return_value={"success": True, "logins": ["alicegh", "bobgh"]},
        ):
            sync_single_github_team_webhook(
                installation_id="998877",
                action="edited",
                github_org_login="PostHog",
                github_team_id=502,
                github_team_slug="team-growth-eng",
                github_team_name="Growth Engineering",
            )
            sync_single_github_team_webhook(
                installation_id="998877",
                action="deleted",
                github_org_login="PostHog",
                github_team_id=501,
                github_team_slug="team-security",
                github_team_name="Team Security",
            )

        renamed = likely_role("@posthog/team-growth-eng", team_id=self.team.id)
        assert renamed is not None
        assert renamed.id == matched_growth.id
        assert renamed.name == "Growth Engineering"
        assert set(RoleMembership.objects.filter(role_id=renamed.id).values_list("user_id", flat=True)) == {
            self.alice.id,
            self.bob.id,
        }

        # Deleted team 501 marks reference orphaned while keeping Security role + its members intact
        security_ref.refresh_from_db()
        assert security_ref.orphaned_at is not None
        assert Role.objects.filter(id=manual_security.id).exists()
        assert set(RoleMembership.objects.filter(role=manual_security).values_list("user_id", flat=True)) == {
            self.alice.id,
            self.bob.id,
        }

    def test_reports_missing_members_permission_when_not_granted(self) -> None:
        other_org_team = self.organization.teams.first()
        assert other_org_team is not None
        IntegrationManager.github.oauth.delete(self.team.id, self.integration.id, ignore_usages=True)
        IntegrationManager.github.oauth.create(
            self.team.id,
            external_id="112233",
            config={
                "account": {"name": "PostHog", "type": "Organization"},
                "installation_id": 112233,
                "permissions": {"contents": "write", "pull_requests": "write"},
            },
            created_by_id=self.alice.id,
        )

        outcome = sync_organization_github_roles(organization_id=self.organization.id, interactive=True)
        assert outcome.skipped_missing_members_permission is True
        assert outcome.created_roles == 0

    def test_app_config_registers_periodic_github_role_sync_with_expiry(self) -> None:
        from unittest.mock import MagicMock

        from products.access_control.backend.apps import _register_periodic_tasks
        from products.access_control.backend.tasks.schedules import GITHUB_ROLE_SYNC_CRONTAB

        sender = MagicMock()
        _register_periodic_tasks(sender)
        sender.add_periodic_task.assert_called_once()
        call = sender.add_periodic_task.call_args
        assert call.args[0] == GITHUB_ROLE_SYNC_CRONTAB
        assert call.kwargs["name"] == "sync github organization team roles"
        assert call.kwargs["expires"] > 0
