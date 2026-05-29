from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.pulse import SENSITIVITY_PRESETS, DetectionMode, PulseDigest, PulseDigestStatus, Sensitivity
from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import TeamScopeError


class TestPulseEnums:
    def test_detection_mode_values(self):
        assert DetectionMode.CHANGE_V1 == "change_v1"
        assert DetectionMode.DISCOVERY == "discovery"

    def test_sensitivity_values(self):
        assert Sensitivity.CONSERVATIVE == "conservative"
        assert Sensitivity.BALANCED == "balanced"
        assert Sensitivity.SENSITIVE == "sensitive"
        assert Sensitivity.CUSTOM == "custom"

    @pytest.mark.parametrize(
        "sensitivity,expected_min_change_pct,expected_robust_z",
        [
            (Sensitivity.CONSERVATIVE, 0.40, 3.5),
            (Sensitivity.BALANCED, 0.25, 3.5),
            (Sensitivity.SENSITIVE, 0.15, 3.0),
        ],
    )
    def test_sensitivity_presets_resolve(self, sensitivity, expected_min_change_pct, expected_robust_z):
        min_change_pct, robust_z = SENSITIVITY_PRESETS[sensitivity]
        assert min_change_pct == expected_min_change_pct
        assert robust_z == expected_robust_z

    def test_custom_has_no_preset_entry(self):
        assert Sensitivity.CUSTOM not in SENSITIVITY_PRESETS


class TestPulseDigestScoping(BaseTest):
    def _make_digest(self) -> PulseDigest:
        now = timezone.now()
        return PulseDigest.objects.create(
            team=self.team,
            period_start=now - timedelta(days=7),
            period_end=now,
            status=PulseDigestStatus.PENDING,
        )

    def test_query_without_team_context_raises(self):
        self._make_digest()
        with pytest.raises(TeamScopeError, match="No team context set"):
            list(PulseDigest.objects.all())

    def test_query_with_team_scope_filters_to_team(self):
        digest = self._make_digest()
        with team_scope(self.team.id):
            assert list(PulseDigest.objects.all()) == [digest]

    def test_for_team_scopes_explicitly(self):
        digest = self._make_digest()
        assert list(PulseDigest.objects.for_team(self.team.id)) == [digest]

    def test_uses_uuid7_id(self):
        # uuid7 ids are version 7; UUIDT (deprecated) is not.
        digest = self._make_digest()
        assert digest.id.version == 7

    def test_delivered_to_field_removed(self):
        field_names = {f.name for f in PulseDigest._meta.get_fields()}
        assert "delivered_to" not in field_names
