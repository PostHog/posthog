from collections.abc import Iterable

import pytest

from parameterized import parameterized

from products.ai_observability.backend.instrumentation_checklist.grading import (
    VOLUME_FLOOR,
    CheckKey,
    ChecklistStats,
    CheckStatus,
    GradedCheck,
    grade_checklist,
)

SESSIONS_WARNING = (
    "No traces include $ai_session_id. If your product has multi-turn conversations, setting it lets us group them "
    "into sessions. Workloads that are complete in one trace, like batch jobs or one-shot generation, do not need it. "
    "Send $ai_session_id as null on those to say so."
)
SESSIONS_OK = "Traces are grouping into sessions."
SESSIONS_OK_DECLINED = "Traces are marked as finishing in one trace, so there is nothing to group."
TOOL_CALLS_WARNING_DECLARED = (
    "No tool calls recorded, but you are sending tool definitions. If your agent does call tools, check that your "
    "SDK version reports them."
)
TOOL_CALLS_WARNING_NOT_DECLARED = (
    "No tool calls recorded. If your app uses tool or function calling, capture it to see which tools run and how "
    "often."
)
TOOL_CALLS_OK = "Tool calls are being recorded."
USER_IDENTITY_WARNING = (
    "Generations are arriving with their trace ID as the distinct ID, so usage and cost cannot be tied to people. "
    "Set distinct_id to your own user identifier."
)
USER_IDENTITY_OK = "AI events are attributed to identified users."
USER_IDENTITY_PENDING = (
    "This check runs once there are 20 generations from a PostHog SDK. Generations sent over OpenTelemetry are not "
    "counted, because we cannot tell whether they are identified."
)
TRACE_STRUCTURE_WARNING = (
    "Without spans, a trace shows LLM calls but not the retrieval, chains or sub-agent steps around them."
)
TRACE_STRUCTURE_OK = "Traces show the steps around your LLM calls."
PENDING_GENERATIONS = "Still collecting data. This check runs once there are 20 generations."
PENDING_AI_EVENTS = "Still collecting data. This check runs once there are 20 AI events."

# The denominator each check floors on, paired with the count that clears its warning.
GENERATION_DENOMINATED = [
    (CheckKey.SESSIONS, "generations", "events_with_session"),
    (CheckKey.TOOL_CALLS, "generations", "generations_with_tool_calls"),
    (CheckKey.USER_IDENTITY, "sdk_generations", "sdk_generations_identified"),
]


def _stats(**overrides: int) -> ChecklistStats:
    counts = {
        "generations": 0,
        "events_with_session": 0,
        "events_declining_session": 0,
        "generations_with_tool_calls": 0,
        "generations_with_tools_declared": 0,
        "sdk_generations": 0,
        "sdk_generations_identified": 0,
        "spans": 0,
        "events_with_parent": 0,
    }
    counts.update(overrides)
    if "total_events" not in overrides:
        counts["total_events"] = counts["generations"] + counts["spans"]
    return ChecklistStats(**counts)


def _graded(stats: ChecklistStats, key: CheckKey, dismissed_keys: Iterable[str] = ()) -> GradedCheck:
    return next(check for check in grade_checklist(stats, dismissed_keys) if check.key == key)


class TestGradeChecklist:
    def test_grades_every_check_exactly_once_in_key_order(self) -> None:
        assert [check.key for check in grade_checklist(_stats(), ())] == list(CheckKey)

    @parameterized.expand(
        [
            (f"{key.value}_{generations}_signal_{signal}", key, denominator, field, generations, signal, expected)
            for key, denominator, field in GENERATION_DENOMINATED
            for generations, signal, expected in [
                (VOLUME_FLOOR - 1, 0, CheckStatus.PENDING),
                (VOLUME_FLOOR - 1, VOLUME_FLOOR - 1, CheckStatus.PENDING),
                (VOLUME_FLOOR, 0, CheckStatus.WARNING),
                (VOLUME_FLOOR, 1, CheckStatus.OK),
                (VOLUME_FLOOR + 1, 0, CheckStatus.WARNING),
            ]
        ]
    )
    def test_volume_floor_boundary_for_generation_denominated_checks(
        self,
        _name: str,
        key: CheckKey,
        denominator: str,
        field: str,
        generations: int,
        signal: int,
        expected: CheckStatus,
    ) -> None:
        stats = _stats(**{"generations": generations, denominator: generations, field: signal})
        assert _graded(stats, key).status == expected

    @parameterized.expand(
        [
            ("below_floor", VOLUME_FLOOR - 1, CheckStatus.PENDING),
            ("at_floor", VOLUME_FLOOR, CheckStatus.WARNING),
            ("above_floor", VOLUME_FLOOR + 1, CheckStatus.WARNING),
        ]
    )
    def test_volume_floor_boundary_for_trace_structure(
        self, _name: str, total_events: int, expected: CheckStatus
    ) -> None:
        stats = _stats(total_events=total_events, spans=0, events_with_parent=0)
        assert _graded(stats, CheckKey.TRACE_STRUCTURE).status == expected

    @parameterized.expand([(key.value, key) for key, *_ in GENERATION_DENOMINATED])
    def test_generation_denominated_checks_stay_pending_at_a_spans_only_project(
        self, _name: str, key: CheckKey
    ) -> None:
        stats = _stats(generations=0, spans=25, events_with_parent=25)
        assert _graded(stats, key).status == CheckStatus.PENDING

    @parameterized.expand(
        [
            ("declined_only", 0, 5, CheckStatus.OK, SESSIONS_OK_DECLINED),
            ("grouped_only", 5, 0, CheckStatus.OK, SESSIONS_OK),
            # A project instrumenting a chat flow while declining its batch job has both, and the
            # grouping it does have is the more useful thing to report.
            ("both", 5, 5, CheckStatus.OK, SESSIONS_OK),
            ("neither", 0, 0, CheckStatus.WARNING, SESSIONS_WARNING),
        ]
    )
    def test_declining_a_session_answers_the_sessions_check(
        self, _name: str, with_session: int, declining: int, expected: CheckStatus, expected_detail: str
    ) -> None:
        stats = _stats(generations=40, events_with_session=with_session, events_declining_session=declining)
        graded = _graded(stats, CheckKey.SESSIONS)
        assert (graded.status, graded.detail) == (expected, expected_detail)

    def test_declining_a_session_cannot_lift_a_project_off_the_volume_floor(self) -> None:
        stats = _stats(generations=VOLUME_FLOOR - 1, events_declining_session=VOLUME_FLOOR - 1)
        assert _graded(stats, CheckKey.SESSIONS).status == CheckStatus.PENDING

    def test_trace_structure_is_graded_at_a_spans_only_project(self) -> None:
        stats = _stats(generations=0, spans=25)
        assert _graded(stats, CheckKey.TRACE_STRUCTURE).status == CheckStatus.OK

    def test_trace_structure_warns_when_only_traces_arrive(self) -> None:
        stats = _stats(generations=0, spans=0, events_with_parent=0, total_events=25)
        assert _graded(stats, CheckKey.TRACE_STRUCTURE).status == CheckStatus.WARNING

    @parameterized.expand(
        [
            ("no_spans_no_parents", 0, 0, CheckStatus.WARNING),
            ("spans_only", 1, 0, CheckStatus.OK),
            ("parents_only", 0, 1, CheckStatus.OK),
            ("both", 9, 4, CheckStatus.OK),
        ]
    )
    def test_trace_structure_warns_only_when_spans_and_parents_are_both_zero(
        self, _name: str, spans: int, events_with_parent: int, expected: CheckStatus
    ) -> None:
        stats = _stats(total_events=100, spans=spans, events_with_parent=events_with_parent)
        assert _graded(stats, CheckKey.TRACE_STRUCTURE).status == expected

    @parameterized.expand(
        [
            (CheckKey.SESSIONS.value, CheckKey.SESSIONS, {"generations": 1000, "events_with_session": 1}),
            (CheckKey.TOOL_CALLS.value, CheckKey.TOOL_CALLS, {"generations": 1000, "generations_with_tool_calls": 1}),
            (
                CheckKey.USER_IDENTITY.value,
                CheckKey.USER_IDENTITY,
                {"generations": 1000, "sdk_generations": 1000, "sdk_generations_identified": 1},
            ),
            (CheckKey.TRACE_STRUCTURE.value, CheckKey.TRACE_STRUCTURE, {"total_events": 1000, "spans": 1}),
        ]
    )
    def test_any_presence_grades_ok_regardless_of_coverage(
        self, _name: str, key: CheckKey, counts: dict[str, int]
    ) -> None:
        assert _graded(_stats(**counts), key).status == CheckStatus.OK

    @parameterized.expand(
        [
            (
                "sessions_warning",
                {"generations": 40},
                CheckKey.SESSIONS,
                CheckStatus.WARNING,
                SESSIONS_WARNING,
            ),
            (
                "sessions_ok",
                {"generations": 40, "events_with_session": 1},
                CheckKey.SESSIONS,
                CheckStatus.OK,
                SESSIONS_OK,
            ),
            (
                "sessions_pending",
                {},
                CheckKey.SESSIONS,
                CheckStatus.PENDING,
                PENDING_GENERATIONS,
            ),
            (
                "tool_calls_warning_with_tools_declared",
                {"generations": 40, "generations_with_tools_declared": 12},
                CheckKey.TOOL_CALLS,
                CheckStatus.WARNING,
                TOOL_CALLS_WARNING_DECLARED,
            ),
            (
                "tool_calls_warning_without_tools_declared",
                {"generations": 40, "generations_with_tools_declared": 0},
                CheckKey.TOOL_CALLS,
                CheckStatus.WARNING,
                TOOL_CALLS_WARNING_NOT_DECLARED,
            ),
            (
                "tool_calls_ok",
                {"generations": 40, "generations_with_tool_calls": 1},
                CheckKey.TOOL_CALLS,
                CheckStatus.OK,
                TOOL_CALLS_OK,
            ),
            (
                "user_identity_warning",
                {"generations": 40, "sdk_generations": 40},
                CheckKey.USER_IDENTITY,
                CheckStatus.WARNING,
                USER_IDENTITY_WARNING,
            ),
            (
                "user_identity_ok",
                {"generations": 40, "sdk_generations": 40, "sdk_generations_identified": 1},
                CheckKey.USER_IDENTITY,
                CheckStatus.OK,
                USER_IDENTITY_OK,
            ),
            (
                # An all-OTel project sits here forever, so this sentence cannot claim data is still coming in.
                "user_identity_pending_at_an_all_otel_project",
                {"generations": 4000, "sdk_generations": 0},
                CheckKey.USER_IDENTITY,
                CheckStatus.PENDING,
                USER_IDENTITY_PENDING,
            ),
            (
                "trace_structure_warning",
                {"total_events": 40},
                CheckKey.TRACE_STRUCTURE,
                CheckStatus.WARNING,
                TRACE_STRUCTURE_WARNING,
            ),
            (
                "trace_structure_ok",
                {"total_events": 40, "spans": 3},
                CheckKey.TRACE_STRUCTURE,
                CheckStatus.OK,
                TRACE_STRUCTURE_OK,
            ),
            (
                "trace_structure_pending",
                {},
                CheckKey.TRACE_STRUCTURE,
                CheckStatus.PENDING,
                PENDING_AI_EVENTS,
            ),
        ]
    )
    def test_detail_copy_matches_status(
        self, _name: str, counts: dict[str, int], key: CheckKey, expected_status: CheckStatus, expected_detail: str
    ) -> None:
        check = _graded(_stats(**counts), key)
        assert check.status == expected_status
        assert check.detail == expected_detail

    @parameterized.expand(
        [
            ("would_be_ok", {"generations": 40, "events_with_session": 40}, SESSIONS_OK),
            ("would_be_warning", {"generations": 40}, SESSIONS_WARNING),
            ("would_be_pending", {}, PENDING_GENERATIONS),
        ]
    )
    def test_dismissal_overrides_every_other_status_but_keeps_the_underlying_detail(
        self, _name: str, counts: dict[str, int], expected_detail: str
    ) -> None:
        check = _graded(_stats(**counts), CheckKey.SESSIONS, dismissed_keys=[CheckKey.SESSIONS])
        assert check.status == CheckStatus.DISMISSED
        assert check.detail == expected_detail

    def test_dismissal_applies_only_to_the_named_check(self) -> None:
        stats = _stats(generations=40)
        assert _graded(stats, CheckKey.TOOL_CALLS, ["tool_calls"]).status == CheckStatus.DISMISSED
        assert _graded(stats, CheckKey.SESSIONS, ["tool_calls"]).status == CheckStatus.WARNING

    @parameterized.expand(
        [
            ("plain_strings", ["sessions"]),
            ("enum_members", [CheckKey.SESSIONS]),
            ("set_of_strings", {"sessions"}),
        ]
    )
    def test_dismissed_keys_accept_strings_and_enum_members(self, _name: str, dismissed_keys: Iterable[str]) -> None:
        assert _graded(_stats(), CheckKey.SESSIONS, dismissed_keys).status == CheckStatus.DISMISSED

    def test_dismissed_keys_may_be_a_single_pass_iterable(self) -> None:
        result = grade_checklist(_stats(), (key for key in ["trace_structure"]))
        assert [check.status for check in result] == [
            CheckStatus.PENDING,
            CheckStatus.PENDING,
            CheckStatus.PENDING,
            CheckStatus.DISMISSED,
        ]

    @parameterized.expand(
        [
            (
                CheckKey.SESSIONS.value,
                CheckKey.SESSIONS,
                {"generations": 40, "events_with_session": 7, "events_declining_session": 2},
            ),
            (
                CheckKey.TOOL_CALLS.value,
                CheckKey.TOOL_CALLS,
                {"generations": 40, "generations_with_tool_calls": 3, "generations_with_tools_declared": 11},
            ),
            (
                CheckKey.USER_IDENTITY.value,
                CheckKey.USER_IDENTITY,
                {"sdk_generations": 31, "sdk_generations_identified": 9},
            ),
            (
                CheckKey.TRACE_STRUCTURE.value,
                CheckKey.TRACE_STRUCTURE,
                {"total_events": 90, "spans": 12, "events_with_parent": 5},
            ),
        ]
    )
    def test_each_check_reports_only_the_counts_it_was_graded_from(
        self, _name: str, key: CheckKey, expected_stats: dict[str, int]
    ) -> None:
        stats = _stats(
            generations=40,
            events_with_session=7,
            events_declining_session=2,
            generations_with_tool_calls=3,
            generations_with_tools_declared=11,
            sdk_generations=31,
            sdk_generations_identified=9,
            spans=12,
            events_with_parent=5,
            total_events=90,
        )
        assert _graded(stats, key).stats == expected_stats


class TestChecklistStats:
    def test_rejects_a_total_below_the_events_it_counted(self) -> None:
        with pytest.raises(ValueError):
            ChecklistStats(
                generations=100,
                events_with_session=0,
                events_declining_session=0,
                generations_with_tool_calls=0,
                generations_with_tools_declared=0,
                sdk_generations=100,
                sdk_generations_identified=0,
                spans=10,
                events_with_parent=0,
                total_events=0,
            )
