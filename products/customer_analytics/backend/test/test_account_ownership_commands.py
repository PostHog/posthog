import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command
from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.team.extensions import get_or_create_team_extension

from products.customer_analytics.backend.facade.enums import AccountRelationshipSource
from products.customer_analytics.backend.logic import ownership, relationships
from products.customer_analytics.backend.logic.ownership_claims import DECISION_COLUMNS
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipDefinition,
    TeamCustomerAnalyticsConfig,
)
from products.customer_analytics.backend.test.factories import create_account, create_saved_query


class TestConfigureAccountOwnershipCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.ae_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="Account executive"
        )

    def _configure(self, *args) -> str:
        out = StringIO()
        call_command("configure_account_ownership", "--team-id", str(self.team.id), *args, stdout=out)
        return out.getvalue()

    def test_binds_roles_and_claim_controls(self):
        view = create_saved_query(
            team_id=self.team.id, name="ownership_decisions", columns=dict.fromkeys(DECISION_COLUMNS, {})
        )

        self._configure(
            "--bind-ae",
            str(self.ae_definition.id),
            "--claims",
            "enabled",
            "--claim-saved-query",
            str(view.id),
        )

        config = get_or_create_team_extension(self.team, TeamCustomerAnalyticsConfig)
        assert config.ae_relationship_definition_id == self.ae_definition.id
        assert config.ownership_claims_enabled is True
        assert config.ownership_claim_saved_query_id == view.id

        self._configure("--unbind-ae")

        assert ownership.role_bindings(self.team.id).ae_definition_id is None

    def test_rejects_a_view_without_the_decision_columns(self):
        view = create_saved_query(team_id=self.team.id, name="partial", columns={"task_id": {}})

        with self.assertRaises(CommandError):
            self._configure("--claim-saved-query", str(view.id))

        assert (
            get_or_create_team_extension(self.team, TeamCustomerAnalyticsConfig).ownership_claim_saved_query_id is None
        )

    def test_binding_is_frozen_while_accounts_manage_the_role(self):
        self._configure("--bind-ae", str(self.ae_definition.id))
        create_account(
            team_id=self.team.id, name="Managed", external_id="org-1", ae_ownership_controlled_at=timezone.now()
        )
        replacement = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="AE 2"
        )

        for args in (["--unbind-ae"], ["--bind-ae", str(replacement.id)]):
            with self.assertRaises(CommandError):
                self._configure(*args)

        assert ownership.role_bindings(self.team.id).ae_definition_id == self.ae_definition.id

    @parameterized.expand(["other_team", "multi_holder", "bound_to_other_role"])
    def test_rejects_an_unusable_definition(self, case):
        if case == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="other")
            definition = AccountRelationshipDefinition.objects.for_team(other_team.id).create(
                team_id=other_team.id, name="AE"
            )
        elif case == "multi_holder":
            definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
                team_id=self.team.id, name="FDE", is_single_holder=False
            )
        else:
            definition = self.ae_definition
            self._configure("--bind-csm", str(definition.id))

        with self.assertRaises(CommandError):
            self._configure("--bind-ae", str(definition.id))

        assert ownership.role_bindings(self.team.id).ae_definition_id is None


class TestAdoptAccountOwnershipCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_user = self._create_user("other@posthog.com")
        self.ae_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="Account executive"
        )
        ownership.bind_role(self.team, "ae", self.ae_definition.id)
        self.empty = create_account(team_id=self.team.id, name="Empty", external_id="org-empty")
        self.held = create_account(team_id=self.team.id, name="Held", external_id="org-held")
        relationships.assign(
            team_id=self.team.id,
            account=self.held,
            definition=self.ae_definition,
            user=self.other_user,
            actor=relationships.Actor.human(self.user),
        )
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.manifest_path = Path(directory) / "manifest.json"

    def _fingerprints(self) -> dict[tuple[str, str], str]:
        out = StringIO()
        call_command("adopt_account_ownership", "--team-id", str(self.team.id), "--export-fingerprints", stdout=out)
        return {(row["account_id"], row["role"]): row["fingerprint"] for row in json.loads(out.getvalue())["roles"]}

    def _write_manifest(self, proposals: list[dict]) -> None:
        self.manifest_path.write_text(json.dumps({"proposals": proposals}))

    def _run(self, *args) -> str:
        out = StringIO()
        call_command(
            "adopt_account_ownership",
            "--team-id",
            str(self.team.id),
            "--manifest",
            str(self.manifest_path),
            *args,
            stdout=out,
        )
        return out.getvalue()

    def _proposals(self) -> list[dict]:
        fingerprints = self._fingerprints()
        return [
            {
                "account_id": str(self.empty.id),
                "role": "ae",
                "state": "assigned",
                "user_id": self.user.id,
                "expected_fingerprint": fingerprints[(str(self.empty.id), "ae")],
            },
            {
                "account_id": str(self.held.id),
                "role": "ae",
                "state": "assigned",
                "user_id": self.other_user.id,
                "expected_fingerprint": fingerprints[(str(self.held.id), "ae")],
            },
        ]

    def _fence(self, account: Account):
        return (
            Account.objects.for_team(self.team.id)
            .values_list("ae_ownership_controlled_at", flat=True)
            .get(pk=account.pk)
        )

    def test_preview_changes_nothing_and_apply_adopts_once(self):
        self._write_manifest(self._proposals())

        preview = self._run()

        assert "preview: would_apply=2" in preview
        assert self._fence(self.empty) is None
        assert not AccountRelationship.objects.for_team(self.team.id).filter(account=self.empty).exists()

        applied = self._run("--apply")

        assert "applied: applied=2" in applied
        seeded = AccountRelationship.objects.for_team(self.team.id).get(account=self.empty, ended_at__isnull=True)
        assert (seeded.user_id, seeded.source) == (self.user.id, AccountRelationshipSource.MIGRATION)
        assert AccountRelationship.objects.for_team(self.team.id).filter(account=self.held).count() == 1
        assert self._fence(self.empty) is not None and self._fence(self.held) is not None
        assert ActivityLog.objects.filter(team_id=self.team.id, activity="role_enrolled").count() == 2

        rerun = self._run("--apply")

        assert "applied: already_applied=2" in rerun
        assert ActivityLog.objects.filter(team_id=self.team.id, activity="role_enrolled").count() == 2

    def test_empty_proposal_confirms_an_empty_role(self):
        fingerprints = self._fingerprints()
        self._write_manifest(
            [
                {
                    "account_id": str(self.empty.id),
                    "role": "ae",
                    "state": "empty",
                    "expected_fingerprint": fingerprints[(str(self.empty.id), "ae")],
                }
            ]
        )

        self._run("--apply")

        assert self._fence(self.empty) is not None
        assert not AccountRelationship.objects.for_team(self.team.id).filter(account=self.empty).exists()

    @parameterized.expand(
        [
            "changed_after_review",
            "held_by_someone_else",
            "held_by_deleted_user",
            "empty_over_deleted_user_row",
            "role_unbound",
            "already_managed",
        ]
    )
    def test_proposal_that_no_longer_holds_is_skipped(self, case):
        for_empty, for_held = self._proposals()
        if case == "role_unbound":
            ownership.bind_role(self.team, "ae", None)
            proposal, expected = for_empty, "invalid (role_unbound)"
        elif case == "already_managed":
            self.held.ae_ownership_controlled_at = timezone.now()
            self.held.save(update_fields=["ae_ownership_controlled_at"])
            for_held["user_id"] = self.user.id
            proposal, expected = for_held, "conflict (role_managed)"
        elif case == "changed_after_review":
            relationships.assign(
                team_id=self.team.id,
                account=self.empty,
                definition=self.ae_definition,
                user=self.other_user,
                actor=relationships.Actor.human(self.user),
            )
            proposal, expected = for_empty, "fingerprint_changed"
        elif case in ("held_by_deleted_user", "empty_over_deleted_user_row"):
            AccountRelationship.objects.for_team(self.team.id).filter(account=self.held).update(user=None)
            if case == "held_by_deleted_user":
                for_held["user_id"] = self.user.id
            else:
                for_held["state"] = "empty"
                del for_held["user_id"]
            for_held["expected_fingerprint"] = self._fingerprints()[(str(self.held.id), "ae")]
            proposal, expected = for_held, "conflict (held_by_deleted_user)"
        else:
            for_held["user_id"] = self.user.id
            for_held["expected_fingerprint"] = self._fingerprints()[(str(self.held.id), "ae")]
            proposal, expected = for_held, f"conflict (held_by_user_{self.other_user.id})"
        self._write_manifest([proposal])
        fence_before = self._fence(self.held)

        output = self._run("--apply")

        assert expected in output
        assert self._fence(self.empty) is None and self._fence(self.held) == fence_before
        holder = AccountRelationship.objects.for_team(self.team.id).get(account=self.held, ended_at__isnull=True)
        deleted_user_cases = ("held_by_deleted_user", "empty_over_deleted_user_row")
        assert holder.user_id == (None if case in deleted_user_cases else self.other_user.id)
