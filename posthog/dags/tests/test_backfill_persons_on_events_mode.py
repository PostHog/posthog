"""Tests for the persons-on-events-mode backfill job."""

from posthog.test.base import BaseTest
from unittest.mock import patch

from dagster import build_op_context

from posthog.schema import PersonsOnEventsMode

from posthog.dags.backfill_persons_on_events_mode import persist_persons_on_events_mode_op
from posthog.models.team import Team


class TestBackfillPersonsOnEventsMode(BaseTest):
    def setUp(self):
        super().setUp()
        # Reset the seeded team so tests start from a known state
        self.team.modifiers = None
        self.team.save()

    def _resolve_default_to(self, mode: PersonsOnEventsMode):
        # Patch the team property used by the op so the test does not depend on the
        # actual feature flag SDK state.
        return patch.object(
            Team,
            "person_on_events_mode_flag_based_default",
            new_callable=lambda: property(lambda _self: mode),
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
