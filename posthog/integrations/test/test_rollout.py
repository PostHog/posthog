from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics import FeatureFlagResult
from prometheus_client import REGISTRY

from posthog.integrations import rollout
from posthog.integrations.rollout import (
    ALL_KINDS,
    DUAL_WRITE_FLAG,
    TeamGone,
    dual_write_enabled,
    dual_write_kinds,
    dual_write_kinds_for_teams,
    require_team_kinds,
    reset_caches,
)
from posthog.models import Team

FLAG_ERRORS = "integrations_service_rollout_flag_errors_total"
MISSING_TEAM_ID = 987_654_321


def _flag_result(payload: Any = None, enabled: bool = True) -> FeatureFlagResult:
    return FeatureFlagResult(key=DUAL_WRITE_FLAG, enabled=enabled, variant=None, payload=payload, reason=None)


def _flag_errors() -> float:
    return REGISTRY.get_sample_value(FLAG_ERRORS) or 0.0


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class TestDualWriteRollout(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        reset_caches()
        self.addCleanup(reset_caches)

    def _flag(
        self,
        result: FeatureFlagResult | None = None,
        side_effect: Any = None,
        definitions: list[dict[str, Any]] | None = None,
    ) -> MagicMock:
        mock = MagicMock(return_value=result, side_effect=side_effect)
        for name, value in (
            ("setup", MagicMock(return_value=MagicMock(disabled=False))),
            ("get_feature_flag_result", mock),
            ("feature_flag_definitions", MagicMock(return_value=definitions)),
        ):
            patcher = patch.object(rollout.posthoganalytics, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return mock

    @parameterized.expand(
        [
            ("dict", {"kinds": ["slack", "github"]}, frozenset({"slack", "github"})),
            ("json_string", '{"kinds": ["slack", "github"]}', frozenset({"slack", "github"})),
            ("json_bytes", b'{"kinds": ["slack"]}', frozenset({"slack"})),
            ("wildcard", {"kinds": ["*"]}, frozenset({ALL_KINDS})),
            ("wildcard_with_other_kinds", {"kinds": ["slack", "*"]}, frozenset({ALL_KINDS})),
            ("empty_kinds", {"kinds": []}, frozenset()),
            ("no_payload", None, frozenset()),
            ("malformed_json", '{"kinds": ["slack"', frozenset()),
            ("json_string_not_object", '"slack"', frozenset()),
            ("list_payload", ["slack"], frozenset()),
            ("missing_kinds_key", {"kind": ["slack"]}, frozenset()),
            ("kinds_not_list", {"kinds": "slack"}, frozenset()),
            ("kind_not_string", {"kinds": ["slack", 1]}, frozenset()),
            ("empty_kind", {"kinds": [""]}, frozenset()),
            ("boolean_payload", True, frozenset()),
            ("deeply_nested_json", "[" * 100_000 + "]" * 100_000, frozenset()),
        ]
    )
    def test_payload_sets_kinds(self, _name: str, payload: Any, expected: frozenset[str]) -> None:
        self._flag(_flag_result(payload))

        assert dual_write_kinds(self.team.id) == expected
        assert dual_write_kinds_for_teams([self.team.id]) == {self.team.id: expected}
        assert require_team_kinds(self.team.id) == expected

    @parameterized.expand(
        [
            ("listed_kind", _flag_result({"kinds": ["slack", "github"]}), "slack", True),
            ("unlisted_kind", _flag_result({"kinds": ["slack", "github"]}), "hubspot", False),
            ("wildcard", _flag_result({"kinds": ["*"]}), "hubspot", True),
            ("flag_off", _flag_result(None, enabled=False), "slack", False),
            ("flag_off_with_false_payload", _flag_result({"kinds": ["*"]}, enabled=False), "slack", False),
            ("malformed", _flag_result("not json"), "slack", False),
        ]
    )
    def test_dual_write_enabled(self, _name: str, result: FeatureFlagResult, kind: str, expected: bool) -> None:
        self._flag(result)

        assert dual_write_enabled(self.team.id, kind) is expected

    def test_evaluates_flag_for_team_with_its_groups(self) -> None:
        evaluate = self._flag(_flag_result({"kinds": ["slack"]}))

        dual_write_kinds(self.team.id)

        evaluate.assert_called_once_with(
            DUAL_WRITE_FLAG,
            str(self.team.uuid),
            groups={"organization": str(self.team.organization_id), "project": str(self.team.id)},
            person_properties={"team_id": str(self.team.id)},
            group_properties={
                "organization": {"id": str(self.team.organization_id)},
                "project": {"id": str(self.team.id)},
            },
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

    @parameterized.expand(
        [
            ("flag_missing", []),
            ("flag_deleted", [{"key": DUAL_WRITE_FLAG, "active": True, "deleted": True}]),
            ("flag_disabled", [{"key": DUAL_WRITE_FLAG, "active": False}]),
            ("other_flags_only", [{"key": "another-flag", "active": True}]),
        ]
    )
    def test_undefined_flag_reads_off_and_is_cached(self, _name: str, definitions: list[dict[str, Any]]) -> None:
        evaluate = self._flag(side_effect=[None, _flag_result({"kinds": ["slack"]})], definitions=definitions)
        errors_before = _flag_errors()

        with self.assertNoLogs(level="WARNING"):
            assert dual_write_kinds(self.team.id) == frozenset()
            assert dual_write_kinds(self.team.id) == frozenset()
        assert evaluate.call_count == 1
        assert _flag_errors() == errors_before

    def test_disabled_sdk_reads_off_and_is_cached(self) -> None:
        assert rollout.posthoganalytics.setup().disabled
        errors_before = _flag_errors()

        with self.assertNoLogs(level="WARNING"):
            assert dual_write_kinds(self.team.id) == frozenset()
        with self.assertNumQueries(0):
            assert dual_write_kinds(self.team.id) == frozenset()
        assert _flag_errors() == errors_before

    @parameterized.expand(
        [
            ("raised_exception", RuntimeError("flag service down"), [{"key": DUAL_WRITE_FLAG, "active": True}]),
            ("no_result_for_active_flag", None, [{"key": DUAL_WRITE_FLAG, "active": True}]),
            ("no_result_definitions_not_loaded", None, None),
        ]
    )
    def test_failed_evaluation_reads_off_and_is_not_cached(
        self, _name: str, failure: Exception | None, definitions: list[dict[str, Any]] | None
    ) -> None:
        evaluate = self._flag(side_effect=[failure, _flag_result({"kinds": ["slack"]})], definitions=definitions)
        errors_before = _flag_errors()

        with self.assertLogs(level="WARNING") as logs:
            assert dual_write_kinds(self.team.id) == frozenset()
        assert _flag_errors() == errors_before + 1
        assert "flag service down" not in "\n".join(logs.output)

        assert dual_write_kinds(self.team.id) == frozenset({"slack"})
        assert evaluate.call_count == 2
        assert _flag_errors() == errors_before + 1

    def test_cache_expires_after_ttl(self) -> None:
        clock = _FakeClock()
        with patch.object(rollout, "_cache", rollout._ExpiringKinds(clock=clock)):
            evaluate = self._flag(_flag_result({"kinds": ["slack"]}))
            assert dual_write_kinds(self.team.id) == frozenset({"slack"})

            evaluate.return_value = _flag_result({"kinds": ["github"]})
            clock.now += rollout.CACHE_TTL_SECONDS - 0.1
            assert dual_write_kinds(self.team.id) == frozenset({"slack"})
            assert evaluate.call_count == 1

            clock.now += 0.1
            assert dual_write_kinds(self.team.id) == frozenset({"github"})
            assert evaluate.call_count == 2

    def test_missing_team_reads_off(self) -> None:
        evaluate = self._flag(_flag_result({"kinds": ["*"]}))

        assert dual_write_kinds(MISSING_TEAM_ID) == frozenset()
        assert dual_write_enabled(MISSING_TEAM_ID, "slack") is False
        assert dual_write_kinds_for_teams([MISSING_TEAM_ID]) == {MISSING_TEAM_ID: frozenset()}
        with self.assertRaises(TeamGone) as raised:
            require_team_kinds(MISSING_TEAM_ID)
        assert raised.exception.team_id == MISSING_TEAM_ID
        evaluate.assert_not_called()

    def test_require_team_kinds_raises_for_missing_team_with_cached_kinds(self) -> None:
        self._flag(_flag_result({"kinds": ["*"]}))
        rollout._cache.put(MISSING_TEAM_ID, frozenset({ALL_KINDS}))

        with self.assertRaises(TeamGone):
            require_team_kinds(MISSING_TEAM_ID)

    def test_bulk_issues_one_team_query_and_one_evaluation_per_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        results = {
            str(self.team.uuid): _flag_result({"kinds": ["slack"]}),
            str(other_team.uuid): _flag_result('{"kinds": ["*"]}'),
        }
        evaluate = self._flag(side_effect=lambda _flag, distinct_id, **_kwargs: results[distinct_id])
        expected = {
            self.team.id: frozenset({"slack"}),
            other_team.id: frozenset({ALL_KINDS}),
            MISSING_TEAM_ID: frozenset(),
        }

        with self.assertNumQueries(1):
            result = dual_write_kinds_for_teams([self.team.id, other_team.id, MISSING_TEAM_ID, self.team.id])
        assert result == expected
        assert evaluate.call_count == 2

        with self.assertNumQueries(1):
            assert dual_write_kinds_for_teams([self.team.id, other_team.id, MISSING_TEAM_ID]) == expected
        assert evaluate.call_count == 2

        with self.assertNumQueries(0):
            assert dual_write_kinds(other_team.id) == frozenset({ALL_KINDS})


class TestExpiringKinds(SimpleTestCase):
    def test_evicts_oldest_entry_at_max_entries(self) -> None:
        cache = rollout._ExpiringKinds(max_entries=2, clock=_FakeClock())
        cache.put(1, frozenset({"slack"}))
        cache.put(2, frozenset({"github"}))
        cache.put(1, frozenset({"hubspot"}))
        cache.put(3, frozenset({"linear"}))

        assert cache.get(1) == frozenset({"hubspot"})
        assert cache.get(2) is None
        assert cache.get(3) == frozenset({"linear"})
