"""Tests for the persons-on-events-mode backfill job."""

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from dagster import build_op_context
from parameterized import parameterized
from posthoganalytics.types import FeatureFlag, FlagMetadata

from posthog.schema import PersonsOnEventsMode

from posthog.dags.backfill_persons_on_events_mode import (
    POE_V1_FLAG,
    POE_V2_FLAG,
    _resolve_persons_on_events_mode,
    persist_persons_on_events_mode_op,
)


def _make_flag(key: str, enabled: bool) -> FeatureFlag:
    """Build a FeatureFlag the way `normalize_flags_response` would."""
    return FeatureFlag(
        key=key,
        enabled=enabled,
        variant=None,
        reason=None,
        metadata=FlagMetadata(id=0, version=1, payload=None, description=""),
    )


class TestResolvePersonsOnEventsMode(BaseTest):
    """Direct tests for the FF→mode mapping in `_resolve_persons_on_events_mode`.

    Mocks the SDK client's `get_flags_decision` with realistic FlagsResponse dicts
    (post-`normalize_flags_response` shape, where each value is a `FeatureFlag` object
    with an `.enabled` bool) so we exercise both the call wiring and the branching logic.
    """

    @parameterized.expand(
        [
            (
                "v2_enabled_takes_precedence",
                {POE_V2_FLAG: _make_flag(POE_V2_FLAG, True), POE_V1_FLAG: _make_flag(POE_V1_FLAG, True)},
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
            (
                "v2_only",
                {POE_V2_FLAG: _make_flag(POE_V2_FLAG, True), POE_V1_FLAG: _make_flag(POE_V1_FLAG, False)},
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
            (
                "v1_when_v2_disabled",
                {POE_V2_FLAG: _make_flag(POE_V2_FLAG, False), POE_V1_FLAG: _make_flag(POE_V1_FLAG, True)},
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
            (
                "fallback_when_both_false",
                {POE_V2_FLAG: _make_flag(POE_V2_FLAG, False), POE_V1_FLAG: _make_flag(POE_V1_FLAG, False)},
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
            (
                "fallback_when_flags_absent_from_response",
                {},
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
            (
                "v1_when_v2_absent_and_v1_enabled",
                {POE_V1_FLAG: _make_flag(POE_V1_FLAG, True)},
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            ),
        ]
    )
    def test_resolves_mode_from_flag_decision(
        self,
        _name: str,
        flags_dict: dict,
        expected: PersonsOnEventsMode,
    ):
        client = MagicMock()
        client.get_flags_decision.return_value = {"flags": flags_dict, "requestId": "test"}

        result = _resolve_persons_on_events_mode(self.team, client)

        assert result == expected
        # Sanity: the resolver actually called the API
        client.get_flags_decision.assert_called_once()
        call_kwargs = client.get_flags_decision.call_args.kwargs
        assert call_kwargs["distinct_id"] == str(self.team.uuid)
        assert call_kwargs["flag_keys_to_evaluate"] == [POE_V2_FLAG, POE_V1_FLAG]
        assert call_kwargs["groups"] == {
            "organization": str(self.team.organization_id),
            "project": str(self.team.id),
        }


class TestBackfillPersonsOnEventsMode(BaseTest):
    def setUp(self):
        super().setUp()
        # Tests assume the seeded team starts with no PoE modifier.
        self.team.modifiers = None
        self.team.save()

    def _resolver_returns(self, mode: PersonsOnEventsMode):
        return patch(
            "posthog.dags.backfill_persons_on_events_mode._resolve_persons_on_events_mode",
            return_value=mode,
        )

    def test_persists_resolved_mode_when_modifier_unset(self):
        with self._resolver_returns(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS):
            result = persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": False}),
                [self.team.id],
            )

        self.team.refresh_from_db()
        assert (
            self.team.modifiers["personsOnEventsMode"]
            == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS.value
        )
        assert result == {
            "would_update": 1,
            "updated": 1,
            "skipped_already_set": 0,
            "skipped_errored": 0,
            "not_found": 0,
        }

    def test_skips_teams_already_set(self):
        self.team.modifiers = {"personsOnEventsMode": PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED.value}
        self.team.save()

        with self._resolver_returns(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS):
            result = persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": False}),
                [self.team.id],
            )

        self.team.refresh_from_db()
        # Existing modifier preserved — backfill must not overwrite an explicit choice.
        assert (
            self.team.modifiers["personsOnEventsMode"] == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED.value
        )
        assert result["updated"] == 0
        assert result["skipped_already_set"] == 1

    def test_dry_run_writes_nothing(self):
        with self._resolver_returns(PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS):
            result = persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": True}),
                [self.team.id],
            )

        self.team.refresh_from_db()
        assert (self.team.modifiers or {}).get("personsOnEventsMode") is None
        assert result == {
            "would_update": 1,
            "updated": 0,
            "skipped_already_set": 0,
            "skipped_errored": 0,
            "not_found": 0,
        }

    def test_preserves_other_modifier_keys(self):
        self.team.modifiers = {"someOtherKey": "value"}
        self.team.save()

        with self._resolver_returns(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS):
            persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": False}),
                [self.team.id],
            )

        self.team.refresh_from_db()
        assert self.team.modifiers["someOtherKey"] == "value"
        assert (
            self.team.modifiers["personsOnEventsMode"]
            == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS.value
        )

    def test_handles_unknown_team_ids(self):
        with self._resolver_returns(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS):
            result = persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": False}),
                [999_999_999],
            )

        assert result == {
            "would_update": 0,
            "updated": 0,
            "skipped_already_set": 0,
            "skipped_errored": 0,
            "not_found": 1,
        }

    def test_resolver_error_skips_team_without_aborting_batch(self):
        with patch(
            "posthog.dags.backfill_persons_on_events_mode._resolve_persons_on_events_mode",
            side_effect=RuntimeError("flag service down"),
        ):
            result = persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": False}),
                [self.team.id],
            )

        self.team.refresh_from_db()
        assert (self.team.modifiers or {}).get("personsOnEventsMode") is None
        assert result == {
            "would_update": 0,
            "updated": 0,
            "skipped_already_set": 0,
            "skipped_errored": 1,
            "not_found": 0,
        }

    def test_idempotent_on_re_run(self):
        with self._resolver_returns(PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS):
            persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": False}),
                [self.team.id],
            )
            second_result = persist_persons_on_events_mode_op(
                build_op_context(op_config={"dry_run": False}),
                [self.team.id],
            )

        # Second run treats the team as already-set; no further write.
        assert second_result["updated"] == 0
        assert second_result["skipped_already_set"] == 1
