import asyncio
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib import admin as django_admin
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.context_layer.backend.admin import ContextLayerConfigAdmin
from products.context_layer.backend.models import ContextLayerConfig
from products.context_layer.backend.temporal import dreaming


class TestDreamPrompt(SimpleTestCase):
    @parameterized.expand(
        [
            (
                None,
                (
                    "This is the first dream: review the last 7 days of organizational activity. "
                    "Treat this as a seed run: include public Space pages that still have no substantive content, "
                    "and fill them only when their channels have qualifying activity in the seed window."
                ),
            ),
            (
                datetime(2026, 8, 20, 3, 0, tzinfo=UTC),
                (
                    "Review organizational activity since 2026-08-20T03:00:00+00:00. "
                    "For completed tasks, recover from 2026-08-13T03:00:00+00:00 so work that completed after an "
                    "earlier review is reconsidered."
                ),
            ),
        ]
    )
    def test_activity_window(self, last_dream_started_at, expected_preamble) -> None:
        assert dreaming._build_dream_prompt(last_dream_started_at).startswith(expected_preamble)

    def test_dream_prompt_carries_both_skills_without_frontmatter(self) -> None:
        prompt = dreaming._build_dream_prompt(None)
        assert "# Context layer dreaming" in prompt
        assert "# Context layer consolidation" in prompt
        assert "channel-list" in prompt
        assert "channel-instructions-retrieve" not in prompt
        assert "A queued, running, test, demo, fixture, or abandoned task is not evidence" in prompt
        assert "never edit, delete, move, or replace them" in prompt
        assert "The server scaffolds every public Space and regenerates its indexes" in prompt
        assert "include every public Space page with no substantive content in the activity scan" in prompt
        assert "at most 100 newest activity items across all channel-scoped sources for each Space" in prompt
        assert "at most 100 newest items from each organization-wide source" in prompt
        assert "next_cursor" in prompt
        assert "offset" in prompt
        assert "name: context-layer-dreaming" not in prompt


class TestDreamCandidates(SimpleTestCase):
    def test_fetch_candidates_caps_each_tick_at_one_thousand(self) -> None:
        configs = [MagicMock(last_dream_started_at=None, organization_id=index) for index in range(1001)]
        queryset = MagicMock()
        queryset.order_by.return_value = configs

        with (
            patch.object(dreaming.ContextLayerConfig.objects, "filter", return_value=queryset),
            patch.object(dreaming.context_layer_facade, "is_context_layer_enabled", return_value=True),
            patch.object(dreaming, "_capture_lane_event") as capture_mock,
        ):
            candidates = dreaming._fetch_dream_candidates()

        assert len(candidates) == 1000
        assert candidates[-1] == "999"
        capture_mock.assert_called_once_with(
            dreaming.COORDINATOR_DISTINCT_ID,
            "context layer dream dispatch cap reached",
            {"cap": 1000},
        )


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
        scoped = MagicMock()
        capture = scoped.return_value.__enter__.return_value
        with patch.object(dreaming, "ph_scoped_capture", scoped):
            for expected_streak in range(1, dreaming.FAILURE_STREAK_PAUSE_THRESHOLD + 1):
                dreaming._record_dispatch_failure(config)
                config.refresh_from_db()
                assert config.dream_failure_streak == expected_streak
        assert config.dreaming_paused is True
        paused_calls = [
            call for call in capture.call_args_list if call.kwargs["event"] == "context layer dreaming paused"
        ]
        assert len(paused_calls) == 1
        assert paused_calls[0].kwargs["properties"]["streak"] == dreaming.FAILURE_STREAK_PAUSE_THRESHOLD

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

    def test_dispatch_prompt_carries_the_activity_window(self) -> None:
        config = self._config()
        target = dreaming._DreamDispatchTarget(config=config, team_id=self.team.id, user_id=self.user.id)
        trigger_mock = AsyncMock()
        with (
            patch.object(dreaming, "_prepare_dispatch", return_value=target),
            patch.object(dreaming, "_record_dispatch_success"),
            patch.object(dreaming, "_capture_lane_event"),
            patch("products.context_layer.backend.enablement.import_channel_context", return_value=[]),
            patch("products.tasks.backend.facade.agents.create_task_and_trigger", trigger_mock),
        ):
            result = asyncio.run(
                dreaming.dispatch_dream_run(dreaming.DispatchDreamRunInput(organization_id=str(self.organization.id)))
            )
        assert result.dispatched is True
        context = trigger_mock.call_args.args[1]
        assert context.runtime == "acp"
        assert context.runtime_adapter == "codex"
        assert context.model == "gpt-5.6-sol"
        assert context.reasoning_effort == "high"
        assert context.initial_permission_mode == "bypassPermissions"
        prompt = trigger_mock.call_args.args[0]
        assert prompt.startswith(
            "This is the first dream: review the last 7 days of organizational activity. Treat this as a seed run:"
        )
        assert "# Context layer dreaming" in prompt

    def test_admin_unpause_action_leaves_the_streak_alone(self) -> None:
        config = self._config(dreaming_paused=True, dream_failure_streak=dreaming.FAILURE_STREAK_PAUSE_THRESHOLD)
        model_admin = ContextLayerConfigAdmin(ContextLayerConfig, django_admin.site)
        model_admin.unpause_dreaming(MagicMock(), ContextLayerConfig.objects.filter(pk=config.pk))
        config.refresh_from_db()
        assert config.dreaming_paused is False
        assert config.dream_failure_streak == dreaming.FAILURE_STREAK_PAUSE_THRESHOLD
