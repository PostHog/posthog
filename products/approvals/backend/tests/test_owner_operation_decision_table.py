"""The owner x operation decision table for feature-flag approval gating.

Which approval family guards a write depends on which product owns the flag. This file
holds that mapping as data and derives every cell from the running code, so the table is
checked rather than described.

Phase 3 proved every entry point behaves alike, so this varies owner and operation over one
entry point (the flag API) instead of multiplying by entry point.

Read DECISION_TABLE as the current, pre-narrowing state: `feature_flag.*` covers every owner.
Narrowing a family to an owner changes cells here, and that diff is the coverage change.
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

GATED_ACTION_KEYS = ("feature_flag.enable", "feature_flag.disable", "feature_flag.update")

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

OPERATIONS = ("create_active", "update_gated_field", "enable", "disable", "delete")


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
    #                                   create  update   enable   disable   delete
    "standalone":                  _row(ENABLE,  UPDATE,  ENABLE,  DISABLE,  UNGATED),
    "experiment":                  _row(NA,      UPDATE,  ENABLE,  DISABLE,  UNGATED),
    "survey_owned":                _row(NA,      UPDATE,  ENABLE,  DISABLE,  UNGATED),
    "survey_linked":               _row(NA,      UPDATE,  ENABLE,  DISABLE,  UNGATED),
    "tour_owned":                  _row(NA,      UPDATE,  ENABLE,  DISABLE,  UNGATED),
    "tour_linked":                 _row(NA,      UPDATE,  ENABLE,  DISABLE,  UNGATED),
    "early_access":                _row(NA,      UPDATE,  ENABLE,  DISABLE,  REJECTED),
    "session_recording_reference": _row(NA,      UPDATE,  ENABLE,  DISABLE,  REJECTED),
}
# fmt: on

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
        if operation != "delete":
            return
        assert flag is not None
        deleted = FeatureFlag.objects_including_soft_deleted.get(id=flag.id).deleted
        # An ungated delete must land, or "no change request" would prove nothing. A REJECTED
        # cell must not.
        assert deleted is (expected is UNGATED), f"delete landed={deleted} but the table says {expected}"

    @parameterized.expand([(f"{owner}__{operation}", owner, operation) for owner, operation in CELLS])
    def test_cell(self, _mock_enabled, _name: str, owner: str, operation: str) -> None:
        expected = DECISION_TABLE[owner][operation]
        if expected == NOT_APPLICABLE:
            self.skipTest("a flag has no owner at creation; the create column is covered under standalone")

        flag = None
        if operation != "create_active":
            # enable starts from inactive, everything else from active.
            flag = self._flag(active=operation != "enable")
            self._apply_owner(owner, flag)
            flag.refresh_from_db()
            assert flag_owner_kind(flag) == EXPECTED_OWNER_KIND[owner]

        self._perform(operation, flag)
        self._assert_operation_took_effect(operation, flag, expected)

        keys = sorted(ChangeRequest.objects.filter(team=self.team).values_list("action_key", flat=True))
        if expected is UNGATED or expected == REJECTED:
            assert keys == [], f"{owner}/{operation} created {keys}, so it is gated after all"
        else:
            assert keys == [expected], f"{owner}/{operation} gated by {keys}, expected [{expected}]"
