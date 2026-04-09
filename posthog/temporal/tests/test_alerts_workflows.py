import pytest

from posthog.temporal.alerts.workflows import CheckAlertWorkflow, ScheduleAllAlertChecksWorkflow


def test_schedule_all_alert_checks_workflow_is_decorated():
    # @temporalio.workflow.defn sets __temporal_workflow_definition
    assert hasattr(ScheduleAllAlertChecksWorkflow, "__temporal_workflow_definition")
    defn = ScheduleAllAlertChecksWorkflow.__temporal_workflow_definition
    assert defn.name == "schedule-all-alert-checks"


def test_check_alert_workflow_is_decorated():
    assert hasattr(CheckAlertWorkflow, "__temporal_workflow_definition")
    defn = CheckAlertWorkflow.__temporal_workflow_definition
    assert defn.name == "check-alert"


def test_schedule_all_alert_checks_workflow_parses_empty_inputs():
    inputs = ScheduleAllAlertChecksWorkflow.parse_inputs([])
    assert inputs is not None


def test_schedule_all_alert_checks_workflow_parses_json_inputs():
    inputs = ScheduleAllAlertChecksWorkflow.parse_inputs(["{}"])
    assert inputs is not None


def test_check_alert_workflow_parses_inputs_with_slo():
    payload = (
        '{"alert_id":"abc","team_id":1,"distinct_id":"abc","calculation_interval":"hourly","insight_id":42,"slo":null}'
    )
    inputs = CheckAlertWorkflow.parse_inputs([payload])
    assert inputs.alert_id == "abc"
    assert inputs.team_id == 1
    assert inputs.slo is None


# Behavioral tests — implemented in PR2 once the activities have real bodies.
# These names are placeholders so the test file documents the intended coverage.


@pytest.mark.skip(reason="Implementation in PR2 — requires evaluate/notify activity bodies")
def test_schedule_all_alert_checks_dispatches_due_alerts():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_schedule_all_alert_checks_swallows_already_started():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_schedule_all_alert_checks_raises_on_other_failures():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_skip_path_exits_cleanly():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_auto_disable_path_exits_cleanly():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_evaluate_then_notify_happy_path():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_evaluate_success_no_notify():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_evaluate_failure_re_raises():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_notify_failure_does_not_re_run_evaluate():
    pass


@pytest.mark.skip(reason="Implementation in PR2")
def test_check_alert_workflow_emits_slo_completion_properties():
    pass


@pytest.mark.skip(reason="Implementation in PR2 — regression test for orphaned starts")
def test_check_alert_workflow_replay_does_not_double_emit_slo():
    pass
