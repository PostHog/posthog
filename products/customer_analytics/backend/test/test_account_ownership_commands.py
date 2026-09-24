import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import UUID

from posthog.test.base import BaseTest

from django.core.management import CommandError, call_command

from parameterized import parameterized

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.customer_analytics.backend.facade.enums import AccountRelationshipSource
from products.customer_analytics.backend.logic import ownership, relationships
from products.customer_analytics.backend.logic.ownership_claims import DECISION_COLUMNS
from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipControl,
    AccountRelationshipDefinition,
)
from products.customer_analytics.backend.test.factories import (
    create_account,
    create_saved_query,
    enroll_account,
    saved_query_columns,
)


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

    def _state(self, definition: AccountRelationshipDefinition) -> tuple[bool, bool, UUID | None]:
        definition.refresh_from_db()
        return (definition.is_controlled, definition.claims_enabled, definition.claim_saved_query_id)

    def _decision_view(self, team_id: int) -> Any:
        return create_saved_query(
            team_id=team_id, name="ownership_decisions", columns=saved_query_columns(DECISION_COLUMNS)
        )

    def test_controls_definitions_and_binds_claim_views(self):
        view = self._decision_view(self.team.id)
        definition_id = str(self.ae_definition.id)

        self._configure(
            "--control",
            definition_id,
            "--claim-view",
            definition_id,
            str(view.id),
            "--claims",
            definition_id,
            "enabled",
        )

        assert self._state(self.ae_definition) == (True, True, view.id)

        self._configure("--clear-claim-view", definition_id, "--uncontrol", definition_id)

        assert self._state(self.ae_definition) == (False, False, None)

    def test_rejects_a_view_without_the_decision_columns(self):
        view = create_saved_query(team_id=self.team.id, name="partial", columns=saved_query_columns(["task_id"]))

        with self.assertRaises(CommandError):
            self._configure(
                "--control", str(self.ae_definition.id), "--claim-view", str(self.ae_definition.id), str(view.id)
            )

        assert self._state(self.ae_definition) == (False, False, None)

    def test_control_cannot_end_while_accounts_are_enrolled(self):
        self._configure("--control", str(self.ae_definition.id))
        enroll_account(create_account(team_id=self.team.id, name="Managed", external_id="org-1"), self.ae_definition)

        with self.assertRaises(CommandError):
            self._configure("--uncontrol", str(self.ae_definition.id))

        assert self._state(self.ae_definition)[0] is True

    @parameterized.expand(
        [
            ("binding_a_view_to_an_uncontrolled_definition", False, False),
            ("uncontrolling_a_definition_with_a_view", True, True),
            ("enabling_claims_without_a_view", True, False),
            ("binding_a_view_of_another_team", True, False),
            ("binding_a_view_that_fills_another_definition", True, False),
            ("binding_and_clearing_in_one_call", True, False),
            ("naming_a_definition_twice_with_different_views", True, False),
        ]
    )
    def test_a_claim_view_binding_is_refused(self, case, controlled, bound):
        view = self._decision_view(self.team.id)
        definition_id = str(self.ae_definition.id)
        if controlled:
            self._configure("--control", definition_id)
        if case == "binding_a_view_to_an_uncontrolled_definition":
            args = ["--claim-view", definition_id, str(view.id)]
        elif case == "uncontrolling_a_definition_with_a_view":
            self._configure("--claim-view", definition_id, str(view.id))
            args = ["--uncontrol", definition_id]
        elif case == "enabling_claims_without_a_view":
            args = ["--claims", definition_id, "enabled"]
        elif case == "binding_a_view_of_another_team":
            other_team = Team.objects.create(organization=self.organization, name="other")
            args = ["--claim-view", definition_id, str(self._decision_view(other_team.id).id)]
        elif case == "binding_a_view_that_fills_another_definition":
            AccountRelationshipDefinition.objects.for_team(self.team.id).create(
                team_id=self.team.id, name="CSM", is_controlled=True, claim_saved_query=view
            )
            args = ["--claim-view", definition_id, str(view.id)]
        elif case == "naming_a_definition_twice_with_different_views":
            other = create_saved_query(
                team_id=self.team.id, name="other_decisions", columns=saved_query_columns(DECISION_COLUMNS)
            )
            args = ["--claim-view", definition_id, str(view.id), "--claim-view", definition_id, str(other.id)]
        else:
            args = ["--claim-view", definition_id, str(view.id), "--clear-claim-view", definition_id]

        with self.assertRaises(CommandError):
            self._configure(*args)

        assert self._state(self.ae_definition) == (controlled, False, view.id if bound else None)

    def test_a_view_moves_between_definitions_in_one_call(self):
        view = self._decision_view(self.team.id)
        csm_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="CSM"
        )
        ae_id, csm_id = str(self.ae_definition.id), str(csm_definition.id)
        self._configure("--control", ae_id, "--control", csm_id, "--claim-view", ae_id, str(view.id))

        self._configure("--clear-claim-view", ae_id, "--claim-view", csm_id, str(view.id))

        assert self._state(self.ae_definition) == (True, False, None)
        assert self._state(csm_definition) == (True, False, view.id)

    @parameterized.expand(["other_team", "multi_holder"])
    def test_rejects_an_unusable_definition(self, case):
        if case == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="other")
            definition = AccountRelationshipDefinition.objects.for_team(other_team.id).create(
                team_id=other_team.id, name="AE"
            )
        else:
            definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
                team_id=self.team.id, name="FDE", is_single_holder=False
            )

        with self.assertRaises(CommandError):
            self._configure("--control", str(definition.id))

        assert self._state(definition)[0] is False


class TestAdoptAccountOwnershipCommand(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_user = self._create_user("other@posthog.com")
        self.ae_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="Account executive", is_controlled=True
        )
        self.empty = create_account(team_id=self.team.id, name="Empty", external_id="org-empty")
        self.held = create_account(team_id=self.team.id, name="Held", external_id="org-held")
        self._assign(self.held, self.other_user)
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.manifest_path = Path(directory) / "manifest.json"

    def _assign(self, account: Account, user: User) -> None:
        # A person's edit would enroll the linked account, so the state a manifest reviews comes
        # from an autonomous writer.
        relationships.assign(
            team_id=self.team.id,
            account=account,
            definition=self.ae_definition,
            user=user,
            actor=relationships.Actor(source=AccountRelationshipSource.WORKFLOW),
        )

    def _fingerprints(self) -> dict[str, str]:
        out = StringIO()
        call_command("adopt_account_ownership", "--team-id", str(self.team.id), "--export-fingerprints", stdout=out)
        rows = json.loads(out.getvalue())["relationships"]
        assert {row["definition_id"] for row in rows} == {str(self.ae_definition.id)}
        return {row["account_id"]: row["fingerprint"] for row in rows}

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
                "definition_id": str(self.ae_definition.id),
                "state": "assigned",
                "user_id": self.user.id,
                "expected_fingerprint": fingerprints[str(self.empty.id)],
            },
            {
                "account_id": str(self.held.id),
                "definition_id": str(self.ae_definition.id),
                "state": "assigned",
                "user_id": self.other_user.id,
                "expected_fingerprint": fingerprints[str(self.held.id)],
            },
        ]

    def _fence(self, account: Account):
        return (
            AccountRelationshipControl.objects.for_team(self.team.id)
            .filter(account=account, definition=self.ae_definition)
            .values_list("controlled_at", flat=True)
            .first()
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

    def test_empty_proposal_confirms_an_empty_relationship(self):
        fingerprints = self._fingerprints()
        self._write_manifest(
            [
                {
                    "account_id": str(self.empty.id),
                    "definition_id": str(self.ae_definition.id),
                    "state": "empty",
                    "expected_fingerprint": fingerprints[str(self.empty.id)],
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
            "definition_not_controlled",
            "already_managed",
        ]
    )
    def test_proposal_that_no_longer_holds_is_skipped(self, case):
        for_empty, for_held = self._proposals()
        if case == "definition_not_controlled":
            ownership.set_controlled(self.team.id, self.ae_definition.id, False)
            proposal, expected = for_empty, "invalid (definition_not_controlled)"
        elif case == "already_managed":
            enroll_account(self.held, self.ae_definition)
            for_held["user_id"] = self.user.id
            proposal, expected = for_held, "conflict (role_managed)"
        elif case == "changed_after_review":
            self._assign(self.empty, self.other_user)
            proposal, expected = for_empty, "fingerprint_changed"
        elif case in ("held_by_deleted_user", "empty_over_deleted_user_row"):
            AccountRelationship.objects.for_team(self.team.id).filter(account=self.held).update(user=None)
            if case == "held_by_deleted_user":
                for_held["user_id"] = self.user.id
            else:
                for_held["state"] = "empty"
                del for_held["user_id"]
            for_held["expected_fingerprint"] = self._fingerprints()[str(self.held.id)]
            proposal, expected = for_held, "conflict (held_by_deleted_user)"
        else:
            for_held["user_id"] = self.user.id
            for_held["expected_fingerprint"] = self._fingerprints()[str(self.held.id)]
            proposal, expected = for_held, f"conflict (held_by_user_{self.other_user.id})"
        self._write_manifest([proposal])
        fence_before = self._fence(self.held)

        output = self._run("--apply")

        assert expected in output
        assert self._fence(self.empty) is None and self._fence(self.held) == fence_before
        holder = AccountRelationship.objects.for_team(self.team.id).get(account=self.held, ended_at__isnull=True)
        deleted_user_cases = ("held_by_deleted_user", "empty_over_deleted_user_row")
        assert holder.user_id == (None if case in deleted_user_cases else self.other_user.id)
