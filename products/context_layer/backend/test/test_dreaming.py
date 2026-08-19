from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.context_layer.backend.models import ContextLayerConfig
from products.context_layer.backend.temporal import dreaming


class TestDreamingLane(BaseTest):
    def _config(self, **overrides) -> ContextLayerConfig:
        defaults = {"organization": self.organization, "head_sha": "a" * 40, "created_by": self.user}
        defaults.update(overrides)
        return ContextLayerConfig.objects.create(**defaults)

    @patch("products.context_layer.backend.temporal.dreaming.context_layer_facade.is_context_layer_enabled")
    def test_fetch_candidates_selects_due_enabled_orgs(self, flag_mock) -> None:
        flag_mock.return_value = True
        config = self._config()
        assert dreaming._fetch_dream_candidates() == [str(config.organization_id)]

    @patch("products.context_layer.backend.temporal.dreaming.context_layer_facade.is_context_layer_enabled")
    def test_fetch_candidates_skips_paused_dreamt_today_and_flag_off(self, flag_mock) -> None:
        flag_mock.return_value = True
        paused = self._config(dreaming_paused=True)
        assert dreaming._fetch_dream_candidates() == []

        paused.dreaming_paused = False
        paused.last_dream_started_at = timezone.now()
        paused.save()
        assert dreaming._fetch_dream_candidates() == []

        paused.last_dream_started_at = timezone.now() - timedelta(days=1)
        paused.save()
        flag_mock.return_value = False
        assert dreaming._fetch_dream_candidates() == []

    def test_dispatch_failure_streak_pauses_the_lane(self) -> None:
        config = self._config()
        for expected_streak in range(1, dreaming.FAILURE_STREAK_PAUSE_THRESHOLD + 1):
            dreaming._record_dispatch_failure(config)
            config.refresh_from_db()
            assert config.dream_failure_streak == expected_streak
        assert config.dreaming_paused is True

        dreaming._record_dispatch_success(config)
        config.refresh_from_db()
        assert config.dream_failure_streak == 0
        assert config.last_dream_started_at is not None

    def test_unpaused_lane_gets_a_fresh_threshold_before_repausing(self) -> None:
        config = self._config(dream_failure_streak=dreaming.FAILURE_STREAK_PAUSE_THRESHOLD, dreaming_paused=False)
        for expected_paused in [False] * (dreaming.FAILURE_STREAK_PAUSE_THRESHOLD - 1) + [True]:
            dreaming._record_dispatch_failure(config)
            config.refresh_from_db()
            assert config.dreaming_paused is expected_paused

    def test_prepare_dispatch_needs_team_and_enabling_user(self) -> None:
        config = self._config(created_by=None)
        assert dreaming._prepare_dispatch(str(config.organization_id)) is None
        config.refresh_from_db()
        # A lane with no dispatch target trips the breaker instead of retrying silently forever.
        assert config.dream_failure_streak == 1

        config.created_by = self.user
        config.save()
        prepared = dreaming._prepare_dispatch(str(config.organization_id))
        assert prepared is not None
        assert prepared.team_id == self.team.id
        assert prepared.user_id == self.user.id

    def test_dream_prompt_carries_both_skills_without_frontmatter(self) -> None:
        prompt = dreaming._build_dream_prompt()
        assert "# Context layer dreaming" in prompt
        assert "# Context layer consolidation" in prompt
        assert "name: context-layer-dreaming" not in prompt
