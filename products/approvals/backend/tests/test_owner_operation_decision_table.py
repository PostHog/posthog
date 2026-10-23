"""The owner x operation decision table for feature-flag approval gating.

Which approval family guards a write depends on which product owns the flag. This file
holds that mapping as data and derives every cell from the running code, so the table is
checked rather than described.

Phase 3 proved every entry point behaves alike, so this varies owner and operation over one
entry point (the flag API) instead of multiplying by entry point.

There are two tables, because scoping policies by flag owner rolls out one organization at a
time. DECISION_TABLE is what an organization sees before it is rolled out, and
DECISION_TABLE_NARROWED is what it sees after. COVERAGE_CHANGE names every cell that differs,
so the coverage this change removes and the coverage it moves are asserted rather than described.

A release condition change already gates on an unowned flag only, so its column reads the same
in both tables.
"""

from typing import Any, Optional

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.ownership import flag_owner_kind
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

GATED_ACTION_KEYS = (
    "feature_flag.enable",
    "feature_flag.disable",
    "feature_flag.update",
    # The organization holds these as hidden mirrors of its flag policies before it is rolled
    # out, so both tables run against the same set of policies and only the scoping differs.
    "experiment.launch",
    "experiment.pause",
    "experiment.update",
)

# A flag has no owner at the moment it is created, so the create column is not a function of
# owner. It is covered once, under `standalone`, and marked NOT_APPLICABLE elsewhere.
NOT_APPLICABLE = "n/a"
# The write is refused outright, so no approval question arises.
REJECTED = "rejected"
UNGATED = None

OWNERS = (
    "standalone",
    "experiment",
    "survey_owned",
    "survey_linked",
    "tour_owned",
    "tour_linked",
    "early_access",
    "session_recording_reference",
)

OPERATIONS = ("create_active", "update_gated_field", "update_release_condition", "enable", "disable", "delete")

RELEASE_CONDITION = {"key": "email", "type": "person", "operator": "icontains", "value": "@example.com"}


def _row(*cells: Optional[str]) -> dict[str, Optional[str]]:
    """Pair a table row with the operation names, so a row reads as a row."""
    return dict(zip(OPERATIONS, cells, strict=True))


# Which product the ownership derivation reports for each setup. A reference is not ownership,
# so the linked cases and the session-recording case all derive as unowned (None).
EXPECTED_OWNER_KIND: dict[str, Optional[str]] = {
    "standalone": None,
    "experiment": "experiment",
    "survey_owned": "survey",
    "survey_linked": None,
    "tour_owned": "product_tour",
    "tour_linked": None,
    "early_access": "early_access_feature",
    "session_recording_reference": None,
}

# Short names so each row of the table below fits on one line and the columns line up.
ENABLE = "feature_flag.enable"
UPDATE = "feature_flag.update"
DISABLE = "feature_flag.disable"
LAUNCH = "experiment.launch"
PAUSE = "experiment.pause"
EXP_UPD = "experiment.update"
NA = NOT_APPLICABLE

# The decision table. One row per owner, one column per operation, in the order OPERATIONS
# declares. A cell names the action family that gates that write, or:
#   UNGATED   nothing gates it; the write lands unreviewed
#   REJECTED  the write is refused outright, so no approval question arises
#   NA        not a function of owner; see the create note above
#
# Narrowing a family to an owner changes cells here, and that diff is the coverage change.
# fmt: off
DECISION_TABLE: dict[str, dict[str, Optional[str]]] = {
    #                                   create  update   release   enable   disable   delete
    "standalone":                  _row(ENABLE,  UPDATE,  UPDATE,   ENABLE,  DISABLE,  UNGATED),
    "experiment":                  _row(NA,      UPDATE,  UNGATED,  ENABLE,  DISABLE,  UNGATED),
    "survey_owned":                _row(NA,      UPDATE,  UNGATED,  ENABLE,  DISABLE,  UNGATED),
    "survey_linked":               _row(NA,      UPDATE,  UPDATE,   ENABLE,  DISABLE,  UNGATED),
    "tour_owned":                  _row(NA,      UPDATE,  UNGATED,  ENABLE,  DISABLE,  UNGATED),
    "tour_linked":                 _row(NA,      UPDATE,  UPDATE,   ENABLE,  DISABLE,  UNGATED),
    "early_access":                _row(NA,      UPDATE,  UNGATED,  ENABLE,  DISABLE,  REJECTED),
    "session_recording_reference": _row(NA,      UPDATE,  UPDATE,   ENABLE,  DISABLE,  REJECTED),
}

# The same table once the organization evaluates policies by flag owner.
#
# An experiment's flags move family: the `experiment.*` policies are one-for-one mirrors of the
# flag policies, so every cell that moves here stays gated and nobody loses an approval.
#
# A survey's, tour's or early access feature's flags become ungated. Surveys get a family of
# their own next; tours and early access are excluded by decision, not by omission.
#
# A create has no owner yet, so it does not move. A flag a product merely references is unowned,
# so it does not move either. The release condition column already gates on an unowned flag only,
# so it reads the same in both tables and contributes nothing to COVERAGE_CHANGE.
DECISION_TABLE_NARROWED: dict[str, dict[str, Optional[str]]] = {
    #                                   create  update   release   enable   disable   delete
    "standalone":                  _row(ENABLE,  UPDATE,  UPDATE,   ENABLE,  DISABLE,  UNGATED),
    "experiment":                  _row(NA,      EXP_UPD, UNGATED,  LAUNCH,  PAUSE,    UNGATED),
    "survey_owned":                _row(NA,      UNGATED, UNGATED,  UNGATED, UNGATED,  UNGATED),
    "survey_linked":               _row(NA,      UPDATE,  UPDATE,   ENABLE,  DISABLE,  UNGATED),
    "tour_owned":                  _row(NA,      UNGATED, UNGATED,  UNGATED, UNGATED,  UNGATED),
    "tour_linked":                 _row(NA,      UPDATE,  UPDATE,   ENABLE,  DISABLE,  UNGATED),
    "early_access":                _row(NA,      UNGATED, UNGATED,  UNGATED, UNGATED,  REJECTED),
    "session_recording_reference": _row(NA,      UPDATE,  UPDATE,   ENABLE,  DISABLE,  REJECTED),
}
# fmt: on

# Every cell the rollout changes, as (owner, operation, before, after). A cell that moves to
# another family keeps its approval; a cell that becomes UNGATED loses it. Asserting the whole
# set means neither kind can be added or dropped without a reviewer seeing it here.
COVERAGE_CHANGE: set[tuple[str, str, Optional[str], Optional[str]]] = {
    ("experiment", "update_gated_field", UPDATE, EXP_UPD),
    ("experiment", "enable", ENABLE, LAUNCH),
    ("experiment", "disable", DISABLE, PAUSE),
    ("survey_owned", "update_gated_field", UPDATE, UNGATED),
    ("survey_owned", "enable", ENABLE, UNGATED),
    ("survey_owned", "disable", DISABLE, UNGATED),
    ("tour_owned", "update_gated_field", UPDATE, UNGATED),
    ("tour_owned", "enable", ENABLE, UNGATED),
    ("tour_owned", "disable", DISABLE, UNGATED),
    ("early_access", "update_gated_field", UPDATE, UNGATED),
    ("early_access", "enable", ENABLE, UNGATED),
    ("early_access", "disable", DISABLE, UNGATED),
}

CELLS = [(owner, operation) for owner in OWNERS for operation in OPERATIONS]


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestOwnerOperationDecisionTable(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": "role based access"}
        ]
        self.organization.save()
        for action_key in GATED_ACTION_KEYS:
            ApprovalPolicy.objects.create(
                organization=self.organization,
                team=self.team,
                action_key=action_key,
                conditions={},
                approver_config={"quorum": 1, "users": [self.user.id]},
                created_by=self.user,
            )

    def _flag(self, *, active: bool) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="table-flag",
            name="table-flag",
            active=active,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )

    def _apply_owner(self, owner: str, flag: FeatureFlag) -> None:
        if owner == "experiment":
            Experiment.objects.create(team=self.team, name="exp", feature_flag=flag)
        elif owner == "survey_owned":
            Survey.objects.create(team=self.team, name="s", type="popover", targeting_flag=flag)
        elif owner == "survey_linked":
            Survey.objects.create(team=self.team, name="s", type="popover", linked_flag=flag)
        elif owner == "tour_owned":
            ProductTour.objects.create(team=self.team, name="t", internal_targeting_flag=flag)
        elif owner == "tour_linked":
            ProductTour.objects.create(team=self.team, name="t", linked_flag=flag)
        elif owner == "early_access":
            EarlyAccessFeature.objects.create(team=self.team, name="f", stage="beta", feature_flag=flag)
        elif owner == "session_recording_reference":
            self.team.session_recording_linked_flag = {"id": flag.id, "key": flag.key}
            self.team.save()

    def _perform(self, operation: str, flag: Optional[FeatureFlag]) -> None:
        base = f"/api/projects/{self.team.id}/feature_flags/"
        if operation == "create_active":
            self.client.post(base, {"key": "born-active", "name": "born", "active": True}, format="json")
            return

        assert flag is not None
        if operation == "update_gated_field":
            payload: dict[str, Any] = {"filters": {"groups": [{"properties": [], "rollout_percentage": 100}]}}
            self.client.patch(f"{base}{flag.id}/", payload, format="json")
        elif operation == "update_release_condition":
            payload = {"filters": {"groups": [{"properties": [RELEASE_CONDITION], "rollout_percentage": 50}]}}
            self.client.patch(f"{base}{flag.id}/", payload, format="json")
        elif operation == "enable":
            self.client.patch(f"{base}{flag.id}/", {"active": True}, format="json")
        elif operation == "disable":
            self.client.patch(f"{base}{flag.id}/", {"active": False}, format="json")
        elif operation == "delete":
            self.client.patch(f"{base}{flag.id}/", {"deleted": True}, format="json")

    def _assert_operation_took_effect(
        self, operation: str, flag: Optional[FeatureFlag], expected: Optional[str]
    ) -> None:
        """An ungated cell must prove the write landed, or "no change request" means nothing."""
        if operation == "update_release_condition":
            assert flag is not None
            properties = FeatureFlag.objects.get(id=flag.id).filters["groups"][0]["properties"]
            landed = [prop["key"] for prop in properties] == [RELEASE_CONDITION["key"]]
            assert landed is (expected is UNGATED), f"release edit landed={landed} but the table says {expected}"
            return
        if operation != "delete":
            return
        assert flag is not None
        deleted = FeatureFlag.objects_including_soft_deleted.get(id=flag.id).deleted
        # An ungated delete must land, or "no change request" would prove nothing. A REJECTED
        # cell must not.
        assert deleted is (expected is UNGATED), f"delete landed={deleted} but the table says {expected}"

    @parameterized.expand(
        [
            (f"{owner}__{operation}__{'narrowed' if narrowed else 'wide'}", owner, operation, narrowed)
            for owner, operation in CELLS
            for narrowed in (False, True)
        ]
    )
    def test_cell(self, _mock_enabled, _name: str, owner: str, operation: str, narrowed: bool) -> None:
        expected = (DECISION_TABLE_NARROWED if narrowed else DECISION_TABLE)[owner][operation]
        if expected == NOT_APPLICABLE:
            self.skipTest("a flag has no owner at creation; the create column is covered under standalone")

        flag = None
        if operation != "create_active":
            # enable starts from inactive, everything else from active.
            flag = self._flag(active=operation != "enable")
            self._apply_owner(owner, flag)
            flag.refresh_from_db()
            assert flag_owner_kind(flag) == EXPECTED_OWNER_KIND[owner]

        with patch("products.approvals.backend.ownership.scope_by_owner_enabled", return_value=narrowed):
            self._perform(operation, flag)
        self._assert_operation_took_effect(operation, flag, expected)

        keys = sorted(ChangeRequest.objects.filter(team=self.team).values_list("action_key", flat=True))
        if expected is UNGATED or expected == REJECTED:
            assert keys == [], f"{owner}/{operation} created {keys}, so it is gated after all"
        else:
            assert keys == [expected], f"{owner}/{operation} gated by {keys}, expected [{expected}]"

    def test_the_rollout_changes_exactly_the_cells_coverage_change_names(self, _mock_enabled) -> None:
        moved = {
            (owner, operation, DECISION_TABLE[owner][operation], DECISION_TABLE_NARROWED[owner][operation])
            for owner, operation in CELLS
            if DECISION_TABLE[owner][operation] != DECISION_TABLE_NARROWED[owner][operation]
        }
        assert moved == COVERAGE_CHANGE

    def test_narrowing_only_moves_an_experiment_between_families(self, _mock_enabled) -> None:
        """Every cell that keeps an approval is an experiment's, and every other one loses it.

        This is the claim the rollout rests on: the organizations being narrowed keep every
        experiment approval they have today, and what they lose is the coverage of the products
        that get a family later or none at all.
        """
        kept = {(owner, after) for owner, _, _, after in COVERAGE_CHANGE if after is not UNGATED}
        lost = {owner for owner, _, _, after in COVERAGE_CHANGE if after is UNGATED}
        assert {owner for owner, _ in kept} == {"experiment"}
        assert lost == {"survey_owned", "tour_owned", "early_access"}
