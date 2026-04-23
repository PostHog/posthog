from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import Change, ChangeAction, Detail, log_activity
from posthog.models.feature_flag.feature_flag import FeatureFlag
from posthog.models.feature_flag.version_history import (
    RECONSTRUCTABLE_FIELDS,
    VersionHistoryIncomplete,
    VersionNotFound,
    reconstruct_flag_at_version,
)


def _log_flag_update(
    team_id: int,
    org_id,
    user,
    flag: FeatureFlag,
    changes: list[Change],
) -> None:
    log_activity(
        organization_id=org_id,
        team_id=team_id,
        user=user,
        was_impersonated=False,
        item_id=flag.id,
        scope="FeatureFlag",
        activity="updated",
        detail=Detail(changes=changes, name=flag.key),
    )


class TestReconstructFlagAtVersion(BaseTest):
    def _create_flag(self, **kwargs) -> FeatureFlag:
        defaults = {
            "team": self.team,
            "created_by": self.user,
            "key": "test-flag",
            "name": "Test Flag",
            "filters": {"groups": [{"rollout_percentage": 100}]},
            "active": True,
            "version": 1,
        }
        defaults.update(kwargs)
        return FeatureFlag.objects.create(**defaults)

    def _simulate_update(
        self,
        flag: FeatureFlag,
        changes: dict,
    ) -> None:
        assert flag.version is not None
        old_version = flag.version
        new_version = old_version + 1

        activity_changes = [
            Change(type="FeatureFlag", action="changed", field="version", before=old_version, after=new_version)
        ]
        for field, (before, after) in changes.items():
            action: ChangeAction = (
                "created"
                if before is None and after is not None
                else "deleted"
                if before is not None and after is None
                else "changed"
            )
            activity_changes.append(Change(type="FeatureFlag", action=action, field=field, before=before, after=after))

        # Update the flag in the DB
        flag.version = new_version
        for field, (_, after) in changes.items():
            setattr(flag, field, after)
        flag.save()

        _log_flag_update(
            team_id=self.team.id,
            org_id=self.organization.id,
            user=self.user,
            flag=flag,
            changes=activity_changes,
        )

    def test_reconstructable_fields_are_concrete_model_fields(self):
        flag = self._create_flag()
        for field in RECONSTRUCTABLE_FIELDS:
            assert hasattr(flag, field), (
                f"RECONSTRUCTABLE_FIELDS contains '{field}' which is not a concrete attribute on FeatureFlag"
            )

    def test_current_version_returns_current_state(self):
        flag = self._create_flag(version=3)
        result = reconstruct_flag_at_version(flag, target_version=3, team_id=self.team.id)

        assert result["is_historical"] is False
        assert result["version"] == 3
        assert result["key"] == "test-flag"
        assert result["id"] == flag.id

    @parameterized.expand(
        [
            ("below_range", 0),
            ("above_range", 4),
        ]
    )
    def test_version_out_of_range_raises(self, _name, target_version):
        flag = self._create_flag(version=3)

        with self.assertRaises(VersionNotFound):
            reconstruct_flag_at_version(flag, target_version=target_version, team_id=self.team.id)

    def test_null_version_raises(self):
        flag = self._create_flag(version=None)

        with self.assertRaises(VersionHistoryIncomplete):
            reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)

    def test_reconstruct_version_1_from_version_2(self):
        flag = self._create_flag(name="Original Name", version=1)
        self._simulate_update(flag, {"name": ("Original Name", "Updated Name")})

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)

        assert result["is_historical"] is True
        assert result["version"] == 1
        assert result["name"] == "Original Name"
        assert result["created_by"] == self.user.id

    def test_reconstruct_version_1_from_version_3(self):
        flag = self._create_flag(name="V1 Name", active=True, version=1)
        self._simulate_update(flag, {"name": ("V1 Name", "V2 Name")})
        self._simulate_update(flag, {"name": ("V2 Name", "V3 Name"), "active": (True, False)})

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert result["version"] == 1
        assert result["name"] == "V1 Name"
        assert result["active"] is True

    def test_reconstruct_intermediate_version(self):
        flag = self._create_flag(name="V1 Name", active=True, version=1)
        self._simulate_update(flag, {"name": ("V1 Name", "V2 Name")})
        self._simulate_update(flag, {"name": ("V2 Name", "V3 Name")})
        self._simulate_update(flag, {"active": (True, False)})

        result = reconstruct_flag_at_version(flag, target_version=2, team_id=self.team.id)
        assert result["version"] == 2
        assert result["name"] == "V2 Name"
        assert result["active"] is True
        assert result["is_historical"] is True

    def test_reconstruct_complex_filters(self):
        v1_filters = {"groups": [{"rollout_percentage": 50}]}
        v2_filters = {"groups": [{"rollout_percentage": 100, "properties": [{"key": "email", "value": "test"}]}]}

        flag = self._create_flag(filters=v1_filters, version=1)
        self._simulate_update(flag, {"filters": (v1_filters, v2_filters)})

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert result["filters"] == v1_filters

    def test_reconstruct_boolean_field_flips(self):
        flag = self._create_flag(active=True, version=1)
        self._simulate_update(flag, {"active": (True, False)})
        self._simulate_update(flag, {"active": (False, True)})

        v1 = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert v1["active"] is True

        v2 = reconstruct_flag_at_version(flag, target_version=2, team_id=self.team.id)
        assert v2["active"] is False

    def test_reconstruct_field_set_from_none(self):
        flag = self._create_flag(rollback_conditions=None, version=1)
        rollback = {"threshold": 5}
        self._simulate_update(flag, {"rollback_conditions": (None, rollback)})

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert result["rollback_conditions"] is None

    def test_reconstruct_multiple_fields_in_one_update(self):
        flag = self._create_flag(name="V1", active=True, version=1)
        v1_filters = flag.filters
        v2_filters = {"groups": [{"rollout_percentage": 50}]}

        self._simulate_update(
            flag,
            {
                "name": ("V1", "V2"),
                "active": (True, False),
                "filters": (v1_filters, v2_filters),
            },
        )

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert result["name"] == "V1"
        assert result["active"] is True
        assert result["filters"] == v1_filters

    def test_missing_activity_log_raises(self):
        flag = self._create_flag(version=5)
        # No activity log entries exist — can't reconstruct anything before current

        with self.assertRaises(VersionHistoryIncomplete):
            reconstruct_flag_at_version(flag, target_version=2, team_id=self.team.id)

    def test_version_timestamp_for_version_1(self):
        flag = self._create_flag(version=1)
        self._simulate_update(flag, {"name": ("V1", "V2")})

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert result["version_timestamp"] == flag.created_at
        assert result["modified_by"] == self.user.id

    def test_version_timestamp_for_intermediate_version(self):
        flag = self._create_flag(version=1)
        self._simulate_update(flag, {"name": ("V1", "V2")})
        self._simulate_update(flag, {"name": ("V2", "V3")})

        result = reconstruct_flag_at_version(flag, target_version=2, team_id=self.team.id)
        assert result["version_timestamp"] is not None
        assert result["modified_by"] == self.user.id

    def test_reconstruct_all_versions_sequentially(self):
        flag = self._create_flag(name="V1", active=True, version=1)
        self._simulate_update(flag, {"name": ("V1", "V2")})
        self._simulate_update(flag, {"name": ("V2", "V3"), "active": (True, False)})
        self._simulate_update(flag, {"name": ("V3", "V4"), "active": (False, True)})

        v1 = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert v1["name"] == "V1"
        assert v1["active"] is True
        assert v1["version"] == 1

        v2 = reconstruct_flag_at_version(flag, target_version=2, team_id=self.team.id)
        assert v2["name"] == "V2"
        assert v2["active"] is True
        assert v2["version"] == 2

        v3 = reconstruct_flag_at_version(flag, target_version=3, team_id=self.team.id)
        assert v3["name"] == "V3"
        assert v3["active"] is False
        assert v3["version"] == 3

        v4 = reconstruct_flag_at_version(flag, target_version=4, team_id=self.team.id)
        assert v4["name"] == "V4"
        assert v4["active"] is True
        assert v4["version"] == 4
        assert v4["is_historical"] is False

    @parameterized.expand(
        [
            ("none", None, {"groups": []}),
            ("empty_dict", {}, {"groups": []}),
            ("missing_groups_key", {"some_legacy_key": "value"}, {"some_legacy_key": "value", "groups": []}),
        ]
    )
    def test_reconstruct_filters_gets_normalized(self, _name, v1_filters, expected):
        v2_filters = {"groups": [{"rollout_percentage": 100}]}

        flag = self._create_flag(filters=v2_filters, version=1)
        self._simulate_update(flag, {"filters": (v1_filters, v2_filters)})

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert result["filters"] == expected

    def test_reconstruct_field_cleared_to_none(self):
        rollback = {"threshold": 5}
        flag = self._create_flag(rollback_conditions=rollback, version=1)
        self._simulate_update(flag, {"rollback_conditions": (rollback, None)})

        result = reconstruct_flag_at_version(flag, target_version=1, team_id=self.team.id)
        assert result["rollback_conditions"] == {"threshold": 5}
