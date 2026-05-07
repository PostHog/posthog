"""Tests for the persons-on-events-mode backfill job."""

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import override_settings

from dagster import build_op_context

from posthog.schema import PersonsOnEventsMode

from posthog.dags.backfill_persons_on_events_mode import persist_persons_on_events_mode_op


class TestBackfillPersonsOnEventsMode(BaseTest):
    def setUp(self):
        super().setUp()
        # Reset the seeded team so tests start from a known state
        self.team.modifiers = None
        self.team.save()

    def _resolve_default_to(self, mode: PersonsOnEventsMode):
        # Patch the resolver helper used by the op so the test does not depend on the
        # actual feature flag SDK state.
        return patch(
            "posthog.dags.backfill_persons_on_events_mode._resolve_persons_on_events_mode_server_side",
            return_value=mode,
        )

    def test_persists_resolved_mode_when_modifiers_unset(self):
        with self._resolve_default_to(PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS):
            result = persist_persons_on_events_mode_op(build_op_context(), [self.team.id])

        self.team.refresh_from_db()
        assert (
            self.team.modifiers["personsOnEventsMode"]
            == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS.value
        )
        assert result == {"updated": 1, "skipped_already_set": 0, "skipped_errored": 0, "not_found": 0}

    def test_skips_teams_that_already_have_a_value(self):
        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS.value}
        self.team.save()

        with self._resolve_default_to(PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS):
            result = persist_persons_on_events_mode_op(build_op_context(), [self.team.id])

        self.team.refresh_from_db()
        # Existing value is preserved — the op must not overwrite teams that already have one.
        assert (
            self.team.modifiers["personsOnEventsMode"]
            == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS.value
        )
        assert result == {"updated": 0, "skipped_already_set": 1, "skipped_errored": 0, "not_found": 0}

    def test_preserves_existing_unrelated_modifier_keys(self):
        self.team.modifiers = {"useMaterializedViews": True, "optimizeProjections": False}
        self.team.save()

        with self._resolve_default_to(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED):
            persist_persons_on_events_mode_op(build_op_context(), [self.team.id])

        self.team.refresh_from_db()
        assert self.team.modifiers == {
            "useMaterializedViews": True,
            "optimizeProjections": False,
            "personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED.value,
        }

    def test_reports_not_found_for_unknown_team_ids(self):
        with self._resolve_default_to(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED):
            result = persist_persons_on_events_mode_op(build_op_context(), [self.team.id, 9999999])

        assert result["updated"] == 1
        assert result["not_found"] == 1

    def test_is_idempotent(self):
        with self._resolve_default_to(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED):
            first = persist_persons_on_events_mode_op(build_op_context(), [self.team.id])
            second = persist_persons_on_events_mode_op(build_op_context(), [self.team.id])

        assert first["updated"] == 1
        assert second["updated"] == 0
        assert second["skipped_already_set"] == 1

    def test_resolver_evaluates_flags_server_side_not_local_only(self):
        # The whole point of doing this work in a backfill rather than in the request hot
        # path is that we can afford a server-side flag eval. A cold worker with `only_evaluate_locally=True`
        # would resolve every team to None and silently migrate them off their intended mode.
        # This test pins the server-side behavior by asserting the SDK call does NOT pass the
        # local-only flag.
        from posthog.dags.backfill_persons_on_events_mode import _resolve_persons_on_events_mode_server_side

        with patch("posthog.dags.backfill_persons_on_events_mode.is_cloud", return_value=True):
            with patch("posthoganalytics.feature_enabled", return_value=False) as mock_flag:
                _resolve_persons_on_events_mode_server_side(self.team)

        # Both flag calls must omit `only_evaluate_locally` (or pass it as False).
        for call in mock_flag.call_args_list:
            assert call.kwargs.get("only_evaluate_locally", False) is False, (
                f"server-side eval must not pass only_evaluate_locally=True; got call with kwargs: {call.kwargs}"
            )

    def test_resolver_returns_override_on_events_when_v2_flag_true(self):
        from posthog.dags.backfill_persons_on_events_mode import _resolve_persons_on_events_mode_server_side

        with patch("posthog.dags.backfill_persons_on_events_mode.is_cloud", return_value=True):
            # First flag (v2) returns True → expect OVERRIDE_PROPERTIES_ON_EVENTS, second flag is never consulted.
            with patch("posthoganalytics.feature_enabled", side_effect=[True]):
                resolved = _resolve_persons_on_events_mode_server_side(self.team)

        assert resolved == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS

    def test_resolver_returns_no_override_when_only_poe_flag_true(self):
        from posthog.dags.backfill_persons_on_events_mode import _resolve_persons_on_events_mode_server_side

        with patch("posthog.dags.backfill_persons_on_events_mode.is_cloud", return_value=True):
            # v2 flag False, poe flag True → expect NO_OVERRIDE_PROPERTIES_ON_EVENTS.
            with patch("posthoganalytics.feature_enabled", side_effect=[False, True]):
                resolved = _resolve_persons_on_events_mode_server_side(self.team)

        assert resolved == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS

    def test_resolver_returns_joined_default_when_both_flags_false(self):
        from posthog.dags.backfill_persons_on_events_mode import _resolve_persons_on_events_mode_server_side

        with patch("posthog.dags.backfill_persons_on_events_mode.is_cloud", return_value=True):
            with patch("posthoganalytics.feature_enabled", side_effect=[False, False]):
                resolved = _resolve_persons_on_events_mode_server_side(self.team)

        assert resolved == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED

    def test_resolver_honors_env_override_without_consulting_flags(self):
        # PERSON_ON_EVENTS_V2_OVERRIDE / PERSON_ON_EVENTS_OVERRIDE bypass flag eval entirely,
        # mirroring the team property's behavior. The backfill must respect them.
        from posthog.dags.backfill_persons_on_events_mode import _resolve_persons_on_events_mode_server_side

        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True, PERSON_ON_EVENTS_OVERRIDE=None):
            with patch("posthog.dags.backfill_persons_on_events_mode.is_cloud", return_value=True):
                with patch("posthoganalytics.feature_enabled") as mock_flag:
                    resolved = _resolve_persons_on_events_mode_server_side(self.team)

        assert resolved == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
        mock_flag.assert_not_called()
