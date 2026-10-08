from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Team

from products.approvals.backend.actions.feature_flags import (
    DisableFeatureFlagAction,
    EnableFeatureFlagAction,
    UpdateFeatureFlagAction,
    _resolve_existing_flag,
)
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.approvals.backend.policies import PolicyEngine
from products.approvals.backend.services import ChangeRequestService
from products.cohorts.backend.models.cohort import Cohort
from products.dashboards.backend.models.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

SINGLE_DICT_PATHS = {"holdout"}

GROUP_KEY_FILTER: dict[str, Any] = {
    "key": "$group_key",
    "type": "group",
    "operator": "exact",
    "value": ["acme"],
    "group_type_index": 0,
}
PROVIDER_FILTER: dict[str, Any] = {
    "key": "provider_id",
    "type": "group",
    "operator": "exact",
    "value": ["provider-1"],
    "group_type_index": 0,
}


def _condition_set(*properties: dict[str, Any], **fields: Any) -> dict[str, Any]:
    return {"properties": list(properties), "rollout_percentage": 100, **fields}


def _build_filters_for_path(path_spec: tuple, rollout_percentage: int) -> dict[str, Any]:
    """Build a filters dict with the rollout_percentage at the specified path."""
    array_path, field_name = path_spec[:-1], path_spec[-1]
    item = {"properties": [], field_name: rollout_percentage}

    # holdout is a single dict, not a list of dicts
    if array_path and array_path[0] in SINGLE_DICT_PATHS:
        current: Any = item
    else:
        current = [item]
    for key in reversed(array_path):
        current = {key: current}

    # Ensure groups key exists
    filters: dict[str, Any] = {"groups": [], **current}
    return filters


class TestUpdateFeatureFlagActionDetect(APIBaseTest):
    def _create_flag(self, filters: dict[str, Any] | None = None) -> FeatureFlag:
        default_filters = {
            "groups": [{"properties": [], "rollout_percentage": 50}],
        }
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters=filters or default_filters,
            created_by=self.user,
        )

    def _mock_request(self, method: str, data: dict[str, Any]) -> MagicMock:
        request = MagicMock()
        request.method = method
        request.data = data
        return request

    def _mock_view(self, flag: FeatureFlag) -> MagicMock:
        view = MagicMock()
        view.get_object.return_value = flag
        view.team = self.team
        return view

    @parameterized.expand(UpdateFeatureFlagAction.ROLLOUT_PERCENTAGE_PATHS)
    def test_detect_returns_true_for_rollout_percentage_change(self, *path_spec):
        old_filters = _build_filters_for_path(path_spec, rollout_percentage=50)
        new_filters = _build_filters_for_path(path_spec, rollout_percentage=80)

        flag = self._create_flag(old_filters)
        request = self._mock_request("PATCH", {"filters": new_filters})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is True

    def test_detect_returns_false_for_enable_disable_only_operations(self):
        flag = self._create_flag()
        flag.active = False
        flag.save()

        request = self._mock_request("PATCH", {"active": True})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is False

    def test_detect_returns_false_for_get_requests(self):
        flag = self._create_flag()
        request = self._mock_request("GET", {})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is False

    def test_detect_returns_false_when_no_gateable_fields_changed(self):
        flag = self._create_flag({"groups": [{"properties": [], "rollout_percentage": 50}]})
        request = self._mock_request("PATCH", {"name": "Updated Name"})
        view = self._mock_view(flag)

        result = UpdateFeatureFlagAction.detect(request, view)

        assert result is False

    @parameterized.expand(
        [
            (
                "property_value_edited",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set({**GROUP_KEY_FILTER, "value": ["acme-2"]})],
                {},
                {},
                True,
            ),
            (
                "operator_edited",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set({**GROUP_KEY_FILTER, "operator": "is_not"})],
                {},
                {},
                True,
            ),
            (
                "property_added",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER, PROVIDER_FILTER)],
                {},
                {},
                True,
            ),
            (
                "property_removed",
                [_condition_set(GROUP_KEY_FILTER, PROVIDER_FILTER)],
                [_condition_set(GROUP_KEY_FILTER)],
                {},
                {},
                True,
            ),
            (
                "condition_set_added",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER), _condition_set(PROVIDER_FILTER)],
                {},
                {},
                True,
            ),
            (
                "condition_sets_reordered",
                [_condition_set(GROUP_KEY_FILTER), _condition_set(PROVIDER_FILTER)],
                [_condition_set(PROVIDER_FILTER), _condition_set(GROUP_KEY_FILTER)],
                {},
                {},
                True,
            ),
            (
                "match_by_group_type_changed",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER, aggregation_group_type_index=1)],
                {},
                {},
                True,
            ),
            (
                "match_by_device",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER)],
                {},
                {"bucketing_identifier": "device_id"},
                True,
            ),
            (
                "variant_override_set",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER, variant="test")],
                {},
                {},
                True,
            ),
            (
                "early_exit_enabled",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER)],
                {"early_exit": True},
                {},
                True,
            ),
            (
                "feature_enrollment_enabled",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER)],
                {"feature_enrollment": True},
                {},
                True,
            ),
            (
                "properties_reordered",
                [_condition_set(GROUP_KEY_FILTER, PROVIDER_FILTER)],
                [_condition_set(PROVIDER_FILTER, GROUP_KEY_FILTER)],
                {},
                {},
                False,
            ),
            (
                "display_only_keys_added",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set({**GROUP_KEY_FILTER, "label": "Acme", "group_key_names": {"acme": "Acme"}})],
                {},
                {},
                False,
            ),
            (
                "null_operator_is_exact",
                [_condition_set({**GROUP_KEY_FILTER, "operator": None})],
                [_condition_set(GROUP_KEY_FILTER)],
                {},
                {},
                False,
            ),
            (
                "operator_alias",
                [_condition_set({**PROVIDER_FILTER, "operator": "min"})],
                [_condition_set({**PROVIDER_FILTER, "operator": "gte"})],
                {},
                {},
                False,
            ),
            (
                "negation_false_is_absent",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set({**GROUP_KEY_FILTER, "negation": False})],
                {},
                {},
                False,
            ),
            (
                "numeric_key_is_string",
                [_condition_set({**PROVIDER_FILTER, "key": 123})],
                [_condition_set({**PROVIDER_FILTER, "key": "123"})],
                {},
                {},
                False,
            ),
            (
                "set_inherits_flag_match_by",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER, aggregation_group_type_index=0)],
                {},
                {},
                False,
            ),
            (
                "empty_variant_is_none",
                [_condition_set(GROUP_KEY_FILTER, variant="")],
                [_condition_set(GROUP_KEY_FILTER, variant=None)],
                {},
                {},
                False,
            ),
            (
                "description_edited",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER, description="EU accounts")],
                {},
                {},
                False,
            ),
            (
                "null_bucketing_is_distinct_id",
                [_condition_set(GROUP_KEY_FILTER)],
                [_condition_set(GROUP_KEY_FILTER)],
                {},
                {"bucketing_identifier": None},
                False,
            ),
        ]
    )
    def test_detect_release_condition_changes(
        self,
        _name: str,
        old_groups: list[dict[str, Any]],
        new_groups: list[dict[str, Any]],
        new_filters_extra: dict[str, Any],
        new_flag_fields: dict[str, Any],
        expected: bool,
    ):
        flag = self._create_flag({"aggregation_group_type_index": 0, "groups": old_groups})
        new_filters = {"aggregation_group_type_index": 0, "groups": new_groups, **new_filters_extra}
        request = self._mock_request("PATCH", {"filters": new_filters, **new_flag_fields})

        assert UpdateFeatureFlagAction.detect(request, self._mock_view(flag)) is expected


class TestDetectFromValidatedData(APIBaseTest):
    """The gate decorates FeatureFlagSerializer.update(self, instance, validated_data), so the
    actual change lives in validated_data — NOT the raw HTTP request body. Internal callers
    (experiment toggles, ship_variant) drive update() from a POST whose body has no flag delta,
    so detection must read validated_data."""

    def _create_flag(self, *, active: bool = True, filters: dict[str, Any] | None = None) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="vd-flag",
            active=active,
            filters=filters or {"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )

    def _serializer_view(self) -> MagicMock:
        # Serializer-style view: _get_instance reads args[0] when "request" is in context.
        view = MagicMock()
        view.context = {"request": MagicMock(), "get_team": lambda: self.team}
        return view

    def _post_request(self) -> MagicMock:
        # A POST whose body carries no flag delta — the failure mode the fix addresses.
        request = MagicMock()
        request.method = "POST"
        request.data = {}
        return request

    def test_enable_detects_from_validated_data_when_request_body_empty(self):
        flag = self._create_flag(active=False)
        view = self._serializer_view()

        result = EnableFeatureFlagAction.detect(self._post_request(), view, flag, {"active": True})

        assert result is True

    def test_disable_detects_from_validated_data_when_request_body_empty(self):
        flag = self._create_flag(active=True)
        view = self._serializer_view()

        result = DisableFeatureFlagAction.detect(self._post_request(), view, flag, {"active": False})

        assert result is True

    def test_enable_does_not_fire_when_already_active(self):
        flag = self._create_flag(active=True)
        view = self._serializer_view()

        result = EnableFeatureFlagAction.detect(self._post_request(), view, flag, {"active": True})

        assert result is False

    def test_update_detects_rollout_change_from_validated_data(self):
        flag = self._create_flag(filters={"groups": [{"properties": [], "rollout_percentage": 50}]})
        view = self._serializer_view()
        # FeatureFlagSerializer puts the filters change under `get_filters` in validated_data.
        validated_data = {"get_filters": {"groups": [{"properties": [], "rollout_percentage": 90}]}}

        result = UpdateFeatureFlagAction.detect(self._post_request(), view, flag, validated_data)

        assert result is True

    def test_update_extract_intent_reads_get_filters_from_validated_data(self):
        flag = self._create_flag(filters={"groups": [{"properties": [], "rollout_percentage": 50}]})
        view = self._serializer_view()
        validated_data = {"get_filters": {"groups": [{"properties": [], "rollout_percentage": 90}]}}

        intent = UpdateFeatureFlagAction.extract_intent(self._post_request(), view, flag, validated_data)

        assert intent["gated_changes"]["rollout_percentage"][0]["value"] == 90
        # full_request_data is re-applied verbatim, so it must carry the input field name.
        assert intent["full_request_data"]["filters"]["groups"][0]["rollout_percentage"] == 90
        assert "get_filters" not in intent["full_request_data"]

    def test_enable_fires_on_create_born_active(self):
        # A brand-new flag born active is gated (create-as-single-arg, the production shape).
        view = self._serializer_view()

        result = EnableFeatureFlagAction.detect(self._post_request(), view, {"key": "f", "active": True})

        assert result is True

    def test_enable_does_not_fire_on_create_born_disabled(self):
        view = self._serializer_view()

        result = EnableFeatureFlagAction.detect(self._post_request(), view, {"key": "f", "active": False})

        assert result is False


class TestUpdateFeatureFlagActionExtractIntent(APIBaseTest):
    def _create_flag(self, filters: dict[str, Any]) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters=filters,
            created_by=self.user,
        )

    def _mock_request(self, method: str, data: dict[str, Any]) -> MagicMock:
        request = MagicMock()
        request.method = method
        request.data = data
        return request

    def _mock_view(self, flag: FeatureFlag) -> MagicMock:
        view = MagicMock()
        view.get_object.return_value = flag
        view.team = self.team
        return view

    def test_extract_intent_captures_rollout_percentage_from_all_locations(self):
        old_filters = {
            "groups": [{"properties": [], "rollout_percentage": 50}],
            "holdout": {"id": 1, "exclusion_percentage": 70},
            "multivariate": {"variants": [{"key": "control", "rollout_percentage": 50}]},
        }
        flag = self._create_flag(old_filters)

        new_filters = {
            "groups": [{"properties": [], "rollout_percentage": 80}],
            "holdout": {"id": 1, "exclusion_percentage": 70},
            "multivariate": {"variants": [{"key": "control", "rollout_percentage": 60}]},
        }
        request = self._mock_request("PATCH", {"filters": new_filters})
        view = self._mock_view(flag)

        intent = UpdateFeatureFlagAction.extract_intent(request, view)

        assert "current_state" in intent
        assert "gated_changes" in intent
        assert "triggered_paths" in intent
        assert "full_request_data" in intent
        assert "preconditions" in intent
        current_rollouts = intent["current_state"]["rollout_percentage"]
        assert current_rollouts is not None
        assert any(r["path"] == "holdout.exclusion_percentage" for r in current_rollouts)
        assert intent["gated_changes"]["rollout_percentage"] is not None

    def test_extract_intent_includes_triggered_paths(self):
        flag = self._create_flag({"groups": [{"properties": [], "rollout_percentage": 50}]})
        request = self._mock_request("PATCH", {"filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}})
        view = self._mock_view(flag)

        intent = UpdateFeatureFlagAction.extract_intent(request, view)

        assert len(intent["triggered_paths"]) > 0
        assert any("groups" in path for path in intent["triggered_paths"])

    @parameterized.expand(
        [
            ("stale_caller", {"version": 2}, 2, True),
            ("current_caller", {"version": 3}, 3, False),
            ("caller_without_version", {}, 3, False),
        ]
    )
    def test_intent_records_the_version_the_caller_edited(
        self, _name: str, caller_fields: dict[str, Any], expected_version: int, expected_stale: bool
    ):
        flag = self._create_flag({"groups": [_condition_set(GROUP_KEY_FILTER)]})
        FeatureFlag.objects.filter(pk=flag.pk).update(version=3)
        flag.refresh_from_db()
        body = {"filters": {"groups": [_condition_set(PROVIDER_FILTER)]}, **caller_fields}

        intent = UpdateFeatureFlagAction.extract_intent(self._mock_request("PATCH", body), self._mock_view(flag))

        assert intent["preconditions"]["version"] == expected_version
        assert UpdateFeatureFlagAction.check_staleness(intent, {"instance": flag}) is expected_stale


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestRelatedFieldsInIntent(APIBaseTest):
    def test_gated_update_stores_related_field_as_primary_keys_then_applies(self, _mock_enabled):
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Flag analytics", created_by=self.user)
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            active=False,
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"active": True, "analytics_dashboards": [dashboard.id]},
            format="json",
        )

        assert response.status_code == 409, response.content
        assert response.json().get("code") == "approval_required"

        change_request = ChangeRequest.objects.get(action_key="feature_flag.enable")
        assert change_request.intent["full_request_data"]["analytics_dashboards"] == [dashboard.id]

        assert FeatureFlag.objects.get(team=self.team, key="test-flag").active is False

        # Apply replays the stored intent through the serializer, so the related field has to survive the round trip.
        result = ChangeRequestService(change_request, self.user).approve()
        assert result.status == "applied"

        applied_flag = FeatureFlag.objects.get(team=self.team, key="test-flag")
        assert applied_flag.active is True
        assert list(applied_flag.analytics_dashboards.all()) == [dashboard]


class TestUpdateFeatureFlagActionDisplayData(APIBaseTest):
    @parameterized.expand(
        [
            (
                "rollout",
                {"rollout_percentage": [{"path": "groups[0].rollout_percentage", "value": 50}]},
                {"rollout_percentage": [{"path": "groups[0].rollout_percentage", "value": 80}]},
                ["groups[0].rollout_percentage"],
                "Update rollout percentage for feature flag 'test-flag': "
                "rollout percentage at groups[0].rollout_percentage: 50% -> 80%",
            ),
            (
                "release_conditions",
                {
                    "rollout_percentage": [],
                    "release_conditions": [
                        {"path": "bucketing_identifier", "value": "distinct_id"},
                        {"path": "groups[0]", "value": {"properties": [GROUP_KEY_FILTER]}},
                    ],
                },
                {
                    "rollout_percentage": [],
                    "release_conditions": [
                        {"path": "bucketing_identifier", "value": "device_id"},
                        {"path": "groups[0]", "value": {"properties": []}},
                        {"path": "groups[1]", "value": {"properties": [PROVIDER_FILTER]}},
                    ],
                },
                ["bucketing_identifier", "groups[0]", "groups[1]"],
                "Update release conditions for feature flag 'test-flag': "
                "match by; condition set 1; condition set 2 added",
            ),
        ]
    )
    def test_get_display_data_names_what_changed(
        self,
        _name: str,
        current_state: dict[str, Any],
        gated_changes: dict[str, Any],
        triggered_paths: list[str],
        expected_description: str,
    ):
        intent_data = {
            "flag_key": "test-flag",
            "current_state": current_state,
            "gated_changes": gated_changes,
            "triggered_paths": triggered_paths,
        }

        display_data = UpdateFeatureFlagAction.get_display_data(intent_data)

        assert display_data["description"] == expected_description
        assert display_data["before"] == current_state
        assert display_data["after"] == gated_changes


class TestCheckStaleness(APIBaseTest):
    def _create_flag(self) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )

    @parameterized.expand(
        [
            ("matching_version", 1, 1, False),
            ("mismatched_version", 1, 2, True),
        ]
    )
    def test_staleness_by_version(self, _name, stored_version, current_version, expected_stale):
        flag = self._create_flag()
        flag.version = current_version

        intent = {"preconditions": {"version": stored_version}}
        context = {"instance": flag}

        from products.approvals.backend.actions.feature_flags import EnableFeatureFlagAction

        result = EnableFeatureFlagAction.check_staleness(intent, context)

        assert result is expected_stale

    def test_stale_when_no_instance_in_context(self):
        from products.approvals.backend.actions.feature_flags import EnableFeatureFlagAction

        intent = {"preconditions": {"version": 1}}
        result = EnableFeatureFlagAction.check_staleness(intent, {})

        assert result is True

    def test_not_stale_when_no_stored_version(self):
        from products.approvals.backend.actions.feature_flags import EnableFeatureFlagAction

        flag = self._create_flag()
        intent: dict[str, Any] = {"preconditions": {}}
        context = {"instance": flag}

        result = EnableFeatureFlagAction.check_staleness(intent, context)

        assert result is False

    @parameterized.expand(
        [
            ("matching_version", 1, 1, False),
            ("mismatched_version", 1, 2, True),
        ]
    )
    def test_update_action_staleness_by_version(self, _name, stored_version, current_version, expected_stale):
        flag = self._create_flag()
        flag.version = current_version

        intent = {"preconditions": {"version": stored_version}}
        context = {"instance": flag}

        result = UpdateFeatureFlagAction.check_staleness(intent, context)

        assert result is expected_stale

    def test_update_action_stale_when_no_instance(self):
        intent = {"preconditions": {"version": 1}}
        result = UpdateFeatureFlagAction.check_staleness(intent, {})

        assert result is True

    @parameterized.expand(
        [
            ("adopted by an experiment", "unowned", True, True),
            ("released by its experiment", "experiment", False, True),
            ("owner unchanged", "unowned", False, False),
            ("still owned by the same experiment", "experiment", True, False),
            ("never classified", None, True, False),
        ]
    )
    def test_staleness_by_owner(self, _name, recorded, owned_now, expected_stale):
        flag = self._create_flag()
        if owned_now:
            Experiment.objects.create(team=self.team, name="exp", feature_flag=flag)

        intent = {"preconditions": {"version": flag.version}}
        context = {"instance": flag, "recorded_owner_kind": recorded}

        assert EnableFeatureFlagAction.check_staleness(intent, context) is expected_stale
        assert UpdateFeatureFlagAction.check_staleness(intent, context) is expected_stale

    def test_base_action_check_staleness_always_returns_false(self):
        from products.approvals.backend.actions.base import BaseAction

        result = BaseAction.check_staleness({"preconditions": {"version": 1}}, {})

        assert result is False

    def test_not_stale_for_create_type_request_with_no_instance(self):
        # A create-type request has no flag row yet, so preconditions.version is None and
        # context has no instance. That must not be treated as staleness, or every
        # create-type change request would be marked stale before it's ever approved.
        intent = {"preconditions": {"version": None}}

        result = EnableFeatureFlagAction.check_staleness(intent, {})

        assert result is False

    def test_stale_when_instance_missing_but_version_was_stored(self):
        # An update/enable/disable request whose flag can no longer be resolved
        # (e.g. deleted) genuinely is stale, unlike the create-type case above.
        intent = {"preconditions": {"version": 1}}

        result = EnableFeatureFlagAction.check_staleness(intent, {})

        assert result is True


class TestResolveExistingFlag(APIBaseTest):
    def _make_change_request(self, team: Team, flag_id: int | str | None) -> ChangeRequest:
        return ChangeRequest.objects.create(
            team=team,
            organization=self.organization,
            created_by=self.user,
            action_key="feature_flag.enable",
            resource_type="feature_flag",
            resource_id=None,
            state="pending",
            intent={"flag_id": flag_id, "full_request_data": {}},
            intent_display={"description": "Enable feature flag"},
            policy_snapshot={"quorum": 1, "users": [self.user.id]},
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def test_resolves_flag_owned_by_a_sibling_team_in_the_same_project(self):
        # Multi-environment projects have one FeatureFlag row per team, but the change
        # request can be created against a sibling environment of the same project.
        # A team_id-scoped lookup misses the flag entirely and looks like a deleted
        # resource — resolution must be project-scoped instead.
        sibling_team = Team.objects.create(organization=self.organization, project=self.team.project)
        flag = FeatureFlag.objects.create(team=sibling_team, key="cross-env-flag", created_by=self.user)
        change_request = self._make_change_request(self.team, flag.id)

        resolved = _resolve_existing_flag(change_request)

        assert resolved is not None
        assert resolved.id == flag.id

    def test_returns_none_when_flag_does_not_exist_in_the_project(self):
        change_request = self._make_change_request(self.team, 999999999)

        resolved = _resolve_existing_flag(change_request)

        assert resolved is None


class TestPolicyConditionEvaluation(APIBaseTest):
    def _create_policy_with_conditions(self, conditions: dict[str, Any]) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions=conditions,
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    @parameterized.expand(
        [
            (">", 50, 80, True),
            (">", 50, 50, False),
            (">", 50, 30, False),
            (">=", 50, 50, True),
            (">=", 50, 80, True),
            (">=", 50, 30, False),
            ("<", 50, 30, True),
            ("<", 50, 50, False),
            ("<", 50, 80, False),
            ("<=", 50, 50, True),
            ("<=", 50, 30, True),
            ("<=", 50, 80, False),
            ("==", 50, 50, True),
            ("==", 50, 80, False),
            ("!=", 50, 80, True),
            ("!=", 50, 50, False),
        ]
    )
    def test_before_after_condition_with_operators(
        self, operator: str, threshold: int, after_value: int, expected: bool
    ):
        conditions = {"type": "before_after", "field": "rollout_percentage", "operator": operator, "value": threshold}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 10}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": after_value}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is expected

    @parameterized.expand(
        [
            (">", 10, 50, 80, True),
            (">", 10, 50, 55, False),
            (">=", 10, 50, 60, True),
            ("<", 10, 50, 55, True),
        ]
    )
    def test_change_amount_condition(
        self, operator: str, threshold: int, before_value: int, after_value: int, expected: bool
    ):
        conditions = {"type": "change_amount", "field": "rollout_percentage", "operator": operator, "value": threshold}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": before_value}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": after_value}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is expected

    def test_any_change_condition_triggers_on_field_change(self):
        conditions = {"type": "any_change", "field": "rollout_percentage"}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is True

    def test_any_change_condition_does_not_trigger_when_unchanged(self):
        conditions = {"type": "any_change", "field": "rollout_percentage"}
        policy = self._create_policy_with_conditions(conditions)
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is False

    def test_empty_conditions_gates_all_changes(self):
        policy = self._create_policy_with_conditions({})
        policy_engine = PolicyEngine()

        intent = {
            "current_state": {"rollout_percentage": [{"path": "groups[0]", "value": 50}]},
            "gated_changes": {"rollout_percentage": [{"path": "groups[0]", "value": 80}]},
        }

        result = policy_engine._evaluate_conditions(policy.conditions, intent)

        assert result is True


class TestMultiPolicyConflictDetection(APIBaseTest):
    def _create_flag(self) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )

    def _create_policy(self, action_key: str, conditions: dict[str, Any] | None = None) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions=conditions or {},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_single_policy_match_returns_normal_approval_flow(self, mock_enabled):
        flag = self._create_flag()
        self._create_policy(
            "feature_flag.update", {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50}
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}},
            format="json",
        )

        assert response.status_code in [200, 409]

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_matching_policy_returns_http_400(self, mock_enabled):
        flag = self._create_flag()
        self._create_policy(
            "feature_flag.update", {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50}
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}},
            format="json",
        )

        if response.status_code == 400:
            data = response.json()
            assert data.get("code") == "policy_conflict"
            assert "conflicting_policies" in data


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestReleaseConditionGating(APIBaseTest):
    EMAIL_FILTER: dict[str, Any] = {"key": "email", "type": "person", "operator": "exact", "value": ["a@example.com"]}

    def _create_policies(self, policies: list[tuple[str, dict[str, Any]]]) -> None:
        for action_key, conditions in policies:
            ApprovalPolicy.objects.create(
                organization=self.organization,
                team=self.team,
                action_key=action_key,
                conditions=conditions,
                approver_config={"quorum": 1, "users": [self.user.id]},
                created_by=self.user,
            )

    def _change_request_keys(self) -> list[str]:
        return sorted(ChangeRequest.objects.filter(team=self.team).values_list("action_key", flat=True))

    @parameterized.expand(
        [
            ("no_conditions_gates_it", [("feature_flag.update", {})], False, 409, ["feature_flag.update"]),
            (
                "rollout_change_condition_ignores_it",
                [("feature_flag.update", {"type": "any_change", "field": "rollout_percentage"})],
                False,
                200,
                [],
            ),
            (
                "rollout_threshold_condition_ignores_it",
                [
                    (
                        "feature_flag.update",
                        {"type": "before_after", "field": "rollout_percentage", "operator": ">", "value": 50},
                    )
                ],
                False,
                200,
                [],
            ),
            (
                "rollout_change_amount_condition_ignores_it",
                [
                    (
                        "feature_flag.update",
                        {"type": "change_amount", "field": "rollout_percentage", "operator": "<", "value": 10},
                    )
                ],
                False,
                200,
                [],
            ),
            (
                "enabling_in_the_same_save_conflicts",
                [("feature_flag.enable", {}), ("feature_flag.update", {})],
                True,
                400,
                [],
            ),
        ]
    )
    def test_targeting_only_edit(
        self,
        _mock_enabled: MagicMock,
        _name: str,
        policies: list[tuple[str, dict[str, Any]]],
        also_enable: bool,
        expected_status: int,
        expected_change_requests: list[str],
    ):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="targeted-flag",
            active=not also_enable,
            filters={"groups": [{"properties": [self.EMAIL_FILTER], "rollout_percentage": 100}]},
            created_by=self.user,
        )
        self._create_policies(policies)
        edited_filter = {**self.EMAIL_FILTER, "value": ["b@example.com"]}
        body: dict[str, Any] = {"filters": {"groups": [{"properties": [edited_filter], "rollout_percentage": 100}]}}
        if also_enable:
            body["active"] = True

        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", body, format="json")

        assert response.status_code == expected_status, response.json()
        assert self._change_request_keys() == expected_change_requests
        flag.refresh_from_db()
        landed = flag.filters["groups"][0]["properties"][0]["value"] == ["b@example.com"]
        assert landed is (expected_status == 200)

    @parameterized.expand(
        [
            ("unchanged", False, 200, []),
            ("enabled_with_unchanged_targeting", True, 409, ["feature_flag.enable"]),
        ]
    )
    def test_saving_the_loaded_flag_back_does_not_gate_its_release_conditions(
        self,
        _mock_enabled: MagicMock,
        _name: str,
        enable: bool,
        expected_status: int,
        expected_change_requests: list[str],
    ):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Paying customers",
            groups=[{"properties": [{"key": "plan", "value": "paid", "type": "person"}]}],
        )
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="loaded-flag",
            active=not enable,
            # Shapes an older write leaves behind: no per-set match by, an operator alias, and no operator.
            filters={
                "groups": [
                    {"properties": [{"key": "id", "type": "cohort", "value": cohort.pk}], "rollout_percentage": 100},
                    {
                        "properties": [
                            {"key": "age", "type": "person", "operator": "min", "value": 18},
                            {"key": "country", "type": "person", "value": ["US"]},
                        ],
                        "rollout_percentage": 30,
                    },
                ]
            },
            created_by=self.user,
        )
        self._create_policies([("feature_flag.enable", {}), ("feature_flag.update", {})])
        url = f"/api/projects/{self.team.id}/feature_flags/{flag.id}/"
        loaded = self.client.get(url).json()
        if enable:
            loaded["active"] = True

        response = self.client.patch(url, loaded, format="json")

        assert response.status_code == expected_status, response.json()
        assert self._change_request_keys() == expected_change_requests


class TestActionRegistrationAndIntegration(APIBaseTest):
    def test_update_feature_flag_action_registered_in_registry(self):
        from products.approvals.backend.actions.registry import ACTION_REGISTRY, register_actions

        register_actions()

        assert "feature_flag.update" in ACTION_REGISTRY
        assert ACTION_REGISTRY["feature_flag.update"] == UpdateFeatureFlagAction

    def test_action_coexists_with_enable_disable_actions(self):
        from products.approvals.backend.actions.registry import ACTION_REGISTRY, register_actions

        register_actions()

        assert "feature_flag.enable" in ACTION_REGISTRY
        assert "feature_flag.disable" in ACTION_REGISTRY
        assert "feature_flag.update" in ACTION_REGISTRY

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_enable_disable_detected_before_update(self, mock_enabled):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            active=False,
            created_by=self.user,
        )

        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"active": True, "filters": {"groups": [{"properties": [], "rollout_percentage": 80}]}},
            format="json",
        )

        if response.status_code == 409:
            response.json()
            change_request = ChangeRequest.objects.filter(action_key="feature_flag.enable").first()
            assert change_request is not None
