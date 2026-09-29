from datetime import timedelta

import pytest

from parameterized import parameterized

from products.alerts.backend.facade.conditions import (
    CONDITION_MEMORY_LIMIT,
    AlertConditionValidationError,
    ConditionBudget,
    ConditionContext,
    build_condition_contexts,
    compile_alert_condition,
    compile_condition_bytecode,
    run_alert_condition,
)

N_OF_M_WITH_RISE_GUARD = """
let breaches := 0
for (let i := 1; i <= 3; i := i + 1) {
  if (values[i] > threshold.count) { breaches := breaches + 1 }
}
return breaches >= 2 and value > previous * 1.05
"""


def _context(**overrides) -> ConditionContext:
    fields = {
        "value": 900.0,
        "values": (900.0, 850.0, 700.0),
        "previous": 850.0,
        "window": {"min": 700.0, "max": 900.0, "avg": 816.6666666666666, "sum": 2450.0, "count": 3.0},
        "labels": {"service_name": "api"},
        "threshold": {"count": 800, "operator": "above"},
        "timestamp": "2026-09-29T10:00:00+00:00",
    }
    fields.update(overrides)
    return ConditionContext(**fields)


def _budget(**overrides) -> ConditionBudget:
    return ConditionBudget(**overrides)


class TestCompileAlertCondition:
    def test_compiles_and_the_program_returns_a_boolean(self) -> None:
        bytecode = compile_alert_condition(N_OF_M_WITH_RISE_GUARD)

        assert run_alert_condition(bytecode, _context(), _budget()).breached is True
        assert (
            run_alert_condition(bytecode, _context(value=855.0, values=(855.0, 850.0, 700.0)), _budget()).breached
            is False
        )

    def test_a_program_that_reads_a_deep_window_compiles(self) -> None:
        # The dry run must offer at least as many windows as a configuration can evaluate.
        assert compile_alert_condition("return values[12] + values[24] > 0")

    @parameterized.expand(
        [
            ("does_not_parse", "return (", "errors"),
            ("empty", "   ", "empty"),
            ("too_long", "return true " + "-- padding\n" * 2000, "long"),
            ("non_boolean", "return 42", "true or false"),
            ("fetch_is_not_available", "return fetch('https://example.com')", "errors"),
        ]
    )
    def test_rejects_a_condition_a_check_cannot_run(self, _name: str, source: str, message: str) -> None:
        with pytest.raises(AlertConditionValidationError) as error:
            compile_alert_condition(source)
        assert message in str(error.value)


class TestRunAlertCondition:
    # Compiled without the dry run, which would reject these programs at write time.

    def test_an_infinite_loop_times_out_and_counts_as_the_users_fault(self) -> None:
        bytecode = compile_condition_bytecode("while (true) {}")

        result = run_alert_condition(bytecode, _context(), _budget(run_timeout=timedelta(milliseconds=100)))

        assert result.breached is None
        assert result.transient is False
        assert "timed out" in (result.error or "")

    def test_memory_growth_is_bounded(self) -> None:
        chunk = "x" * 4096
        bytecode = compile_condition_bytecode(f"let a := []\nwhile (true) {{ a := arrayPushBack(a, '{chunk}') }}")

        result = run_alert_condition(bytecode, _context(), _budget(run_timeout=timedelta(seconds=5)))

        assert result.breached is None
        assert result.transient is False
        assert "memory" in (result.error or "")
        assert CONDITION_MEMORY_LIMIT == 4 * 1024 * 1024

    def test_sleep_is_not_allowed_and_does_not_wait(self) -> None:
        bytecode = compile_condition_bytecode("sleep(2)\nreturn true")

        result = run_alert_condition(bytecode, _context(), _budget())

        assert result.breached is None
        assert result.transient is False
        assert result.duration_ms < 1_000

    def test_a_runtime_error_is_the_users_fault_and_hides_the_values(self) -> None:
        bytecode = compile_condition_bytecode("return values[1] / labels")

        result = run_alert_condition(bytecode, _context(), _budget())

        assert result.breached is None
        assert result.transient is False
        assert "900" not in (result.error or "")

    def test_the_batch_budget_stops_further_runs_and_marks_them_transient(self) -> None:
        bytecode = compile_alert_condition("return true")
        budget = _budget(total=timedelta(microseconds=1))

        first = run_alert_condition(bytecode, _context(), budget)
        second = run_alert_condition(bytecode, _context(), budget)

        assert first.breached is True
        assert second.breached is None
        assert second.transient is True

    def test_the_batch_wall_budget_stops_further_runs_even_with_cpu_budget_left(self) -> None:
        bytecode = compile_alert_condition("return true")
        budget = _budget(wall_total=timedelta(microseconds=1))

        first = run_alert_condition(bytecode, _context(), budget)
        second = run_alert_condition(bytecode, _context(), budget)

        assert first.breached is True
        assert second.breached is None
        assert second.transient is True

    def test_labels_threshold_and_window_stats_are_visible_to_the_program(self) -> None:
        bytecode = compile_alert_condition(
            "return labels.service_name == 'api' and threshold.operator == 'above' and window.max == 900 and window.count == 3"
        )

        assert run_alert_condition(bytecode, _context(), _budget()).breached is True


class TestBuildConditionContexts:
    def test_one_context_per_window_newest_first_and_stats_ignore_none(self) -> None:
        contexts = build_condition_contexts(
            (5.0, None, 3.0, 1.0),
            evaluation_periods=2,
            labels={"a": "1"},
            threshold={"count": 4, "operator": "above"},
            window_ends=("2026-09-29T10:05:00+00:00", "2026-09-29T10:00:00+00:00"),
        )

        assert [c.value for c in contexts] == [5.0, None]
        assert contexts[0].values == (5.0, None, 3.0, 1.0)
        assert contexts[0].previous is None
        assert contexts[1].values == (None, 3.0, 1.0)
        assert contexts[1].previous == 3.0
        assert contexts[0].window == {"min": 1.0, "max": 5.0, "avg": 3.0, "sum": 9.0, "count": 3.0}
        assert contexts[1].timestamp == "2026-09-29T10:00:00+00:00"
        assert contexts[0].as_globals()["values"] == [5.0, None, 3.0, 1.0]
