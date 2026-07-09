"""Tests for the PostHog Code investigation Temporal activities.

Covers: create_posthog_code_investigation_task, get_investigation_run_state,
finalize_posthog_code_investigation, cancel_posthog_code_investigation.

Facade is patched at the module's import site:
    posthog.temporal.alerts.posthog_code_investigation.tasks_facade
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership
from posthog.temporal.alerts import posthog_code_investigation as _mod
from posthog.temporal.alerts.posthog_code_investigation import (
    AlertInvestigationReport,
    PostHogCodeInvestigationInputs,
    cancel_posthog_code_investigation,
    create_posthog_code_investigation_task,
    finalize_posthog_code_investigation,
    get_investigation_run_state,
)

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from products.product_analytics.backend.models.insight import Insight

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PATCH_TARGET = "posthog.temporal.alerts.posthog_code_investigation.tasks_facade"


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-investigation-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-investigation-team")


@pytest.fixture
def owner(organization):
    user = User.objects.create_user(email="owner@example.com", password="x", first_name="Alert", last_name="Owner")
    OrganizationMembership.objects.create(user=user, organization=organization)
    return user


@pytest.fixture
def insight(team):
    return Insight.objects.create(team=team, name="Error rate")


@pytest.fixture
def alert(team, insight, owner):
    return AlertConfiguration.objects.create(
        team=team,
        insight=insight,
        name="Error rate spike",
        investigation_mode=AlertConfiguration.InvestigationMode.POSTHOG_CODE,
        investigation_agent_enabled=True,
        investigation_repository="owner/repo",
        created_by=owner,
    )


@pytest.fixture
def alert_check(alert):
    return AlertCheck.objects.create(
        alert_configuration=alert,
        calculated_value=99.0,
        investigation_status=InvestigationStatus.PENDING,
    )


@pytest.fixture
def env():
    return ActivityEnvironment()


def _fake_create_and_run_task_factory(team, owner):
    """Return a fake ``create_and_run_task`` that builds real ORM rows."""
    from django.apps import apps

    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")

    def _fake(**kwargs):
        task = Task.objects.create(
            team=team,
            title=kwargs.get("title", "t"),
            description=kwargs.get("description", "d"),
            created_by=owner,
            origin_product=Task.OriginProduct.ALERT,
        )
        run = TaskRun.objects.create(task=task, team=team)
        return SimpleNamespace(task_id=task.id, team_id=team.id, latest_run=SimpleNamespace(id=run.id))

    return _fake


def _inputs(team, alert, check) -> PostHogCodeInvestigationInputs:
    return PostHogCodeInvestigationInputs(
        team_id=team.id,
        alert_id=str(alert.id),
        alert_check_id=str(check.id),
    )


# ---------------------------------------------------------------------------
# create_posthog_code_investigation_task
# ---------------------------------------------------------------------------


async def test_create_calls_facade_with_exact_kwargs(env, team, alert, alert_check, owner):
    """The facade must be called with origin_product=ALERT, the right user_id, repository,
    posthog_mcp_scopes='read_only', and output_schema=AlertInvestigationReport."""
    fake = _fake_create_and_run_task_factory(team, owner)
    captured = {}

    def _capturing(**kwargs):
        captured.update(kwargs)
        return fake(**kwargs)

    with patch.object(_mod, "tasks_facade") as mock_facade:
        from products.tasks.backend.facade import api as tasks_facade_real

        mock_facade.TaskOriginProduct = tasks_facade_real.TaskOriginProduct
        mock_facade.create_and_run_task.side_effect = _capturing
        mock_facade.update_task_run_state.return_value = {}

        result = await env.run(create_posthog_code_investigation_task, _inputs(team, alert, alert_check))

    assert result.status == "created"
    assert result.task_run_id is not None

    assert captured["origin_product"].value == "alert"
    assert captured["user_id"] == owner.id
    assert captured["repository"] == "owner/repo"
    assert captured["posthog_mcp_scopes"] == "read_only"
    assert captured["output_schema"] is AlertInvestigationReport
    assert captured["create_pr"] is True
    # title must not exceed 255 chars
    assert len(captured["title"]) <= 255
    assert "Error rate spike" in captured["title"]


async def test_create_is_idempotent_on_retry(env, team, alert, alert_check, owner):
    """If investigation_task_run_id is already set, facade must not be called again."""
    existing_run_id = uuid.uuid4()
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update)(investigation_task_run_id=existing_run_id)

    with patch.object(_mod, "tasks_facade") as mock_facade:
        result = await env.run(create_posthog_code_investigation_task, _inputs(team, alert, alert_check))

    mock_facade.create_and_run_task.assert_not_called()
    assert result.status == "created"
    assert result.task_run_id == str(existing_run_id)


async def test_create_skips_when_no_owner(env, team, insight, alert_check):
    """Alert with no created_by → status=skipped, check updated to SKIPPED."""
    alert_no_owner = await sync_to_async(AlertConfiguration.objects.create)(
        team=team,
        insight=insight,
        name="Ownerless alert",
        investigation_mode=AlertConfiguration.InvestigationMode.POSTHOG_CODE,
        investigation_agent_enabled=True,
        created_by=None,
    )
    check = await sync_to_async(AlertCheck.objects.create)(
        alert_configuration=alert_no_owner,
        calculated_value=1.0,
        investigation_status=InvestigationStatus.PENDING,
    )
    inputs = PostHogCodeInvestigationInputs(
        team_id=team.id,
        alert_id=str(alert_no_owner.id),
        alert_check_id=str(check.id),
    )

    with patch.object(_mod, "tasks_facade") as mock_facade:
        result = await env.run(create_posthog_code_investigation_task, inputs)

    mock_facade.create_and_run_task.assert_not_called()
    assert result.status == "skipped"
    assert result.reason == "no_active_owner"

    await sync_to_async(check.refresh_from_db)()
    assert check.investigation_status == InvestigationStatus.SKIPPED
    assert check.investigation_error == {"reason": "investigation needs an owner"}


async def test_create_skips_when_owner_not_active_member(env, team, insight, organization):
    """Owner exists but is not a member of the team's org → skipped."""
    other_org = await sync_to_async(Organization.objects.create)(name="other-org-inv")
    user = await sync_to_async(User.objects.create_user)(
        email="stranger@example.com", password="x", first_name="Stranger", last_name="User"
    )
    await sync_to_async(OrganizationMembership.objects.create)(user=user, organization=other_org)  # wrong org

    alert = await sync_to_async(AlertConfiguration.objects.create)(
        team=team,
        insight=insight,
        name="Alien alert",
        investigation_mode=AlertConfiguration.InvestigationMode.POSTHOG_CODE,
        investigation_agent_enabled=True,
        created_by=user,
    )
    check = await sync_to_async(AlertCheck.objects.create)(
        alert_configuration=alert,
        calculated_value=1.0,
        investigation_status=InvestigationStatus.PENDING,
    )
    inputs = PostHogCodeInvestigationInputs(
        team_id=team.id,
        alert_id=str(alert.id),
        alert_check_id=str(check.id),
    )

    with patch.object(_mod, "tasks_facade") as mock_facade:
        result = await env.run(create_posthog_code_investigation_task, inputs)

    mock_facade.create_and_run_task.assert_not_called()
    assert result.status == "skipped"
    await sync_to_async(check.refresh_from_db)()
    assert check.investigation_status == InvestigationStatus.SKIPPED


async def test_create_does_not_raise_on_facade_exception(env, team, alert, alert_check, owner):
    """A facade exception → status=failed on check, result.status='failed', no exception raised."""
    with patch.object(_mod, "tasks_facade") as mock_facade:
        from products.tasks.backend.facade import api as tasks_facade_real

        mock_facade.TaskOriginProduct = tasks_facade_real.TaskOriginProduct
        mock_facade.create_and_run_task.side_effect = RuntimeError("sandbox error")

        result = await env.run(create_posthog_code_investigation_task, _inputs(team, alert, alert_check))

    assert result.status == "failed"
    assert result.reason is not None

    await sync_to_async(alert_check.refresh_from_db)()
    assert alert_check.investigation_status == InvestigationStatus.FAILED
    assert "sandbox error" in alert_check.investigation_error["reason"]


async def test_create_fails_gracefully_when_latest_run_is_none(env, team, alert, alert_check, owner):
    """latest_run=None from the facade → status=failed, no exception raised."""
    with patch.object(_mod, "tasks_facade") as mock_facade:
        from products.tasks.backend.facade import api as tasks_facade_real

        mock_facade.TaskOriginProduct = tasks_facade_real.TaskOriginProduct
        mock_facade.create_and_run_task.return_value = SimpleNamespace(
            task_id=uuid.uuid4(), team_id=team.id, latest_run=None
        )

        result = await env.run(create_posthog_code_investigation_task, _inputs(team, alert, alert_check))

    assert result.status == "failed"
    await sync_to_async(alert_check.refresh_from_db)()
    assert alert_check.investigation_status == InvestigationStatus.FAILED


async def test_create_stores_state_updates_on_success(env, team, alert, alert_check, owner):
    """On success, update_task_run_state must be called with alert_id, alert_check_id, etc."""
    fake = _fake_create_and_run_task_factory(team, owner)
    state_updates = {}

    with patch.object(_mod, "tasks_facade") as mock_facade:
        from products.tasks.backend.facade import api as tasks_facade_real

        mock_facade.TaskOriginProduct = tasks_facade_real.TaskOriginProduct
        mock_facade.create_and_run_task.side_effect = fake

        def _capture_state(run_id, *, updates=None, **kwargs):
            state_updates.update(updates or {})
            return {}

        mock_facade.update_task_run_state.side_effect = _capture_state

        await env.run(create_posthog_code_investigation_task, _inputs(team, alert, alert_check))

    assert state_updates.get("alert_id") == str(alert.id)
    assert state_updates.get("alert_check_id") == str(alert_check.id)
    assert "insight_short_id" in state_updates
    assert "dashboard_ids" in state_updates


async def test_create_sets_previous_task_run_id_from_same_episode(
    env, team, alert, alert_check, insight, owner, organization
):
    """previous_task_run_id is taken from the latest earlier check in the same firing episode."""
    from posthog.schema import AlertState

    prev_run_id = uuid.uuid4()
    # Older check with investigation_task_run_id set (same firing episode: no non-FIRING boundary)
    await sync_to_async(AlertCheck.objects.create)(
        alert_configuration=alert,
        calculated_value=50.0,
        state=AlertState.FIRING,
        investigation_task_run_id=prev_run_id,
        investigation_status=InvestigationStatus.DONE,
    )

    captured_kwargs: dict = {}

    def _fake(**kwargs):
        captured_kwargs.update(kwargs)
        from django.apps import apps

        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        task = Task.objects.create(
            team=team,
            title=kwargs.get("title", "t"),
            description=kwargs.get("description", "d"),
            created_by=owner,
            origin_product=Task.OriginProduct.ALERT,
        )
        run = TaskRun.objects.create(task=task, team=team)
        return SimpleNamespace(task_id=task.id, team_id=team.id, latest_run=SimpleNamespace(id=run.id))

    with patch.object(_mod, "tasks_facade") as mock_facade:
        from products.tasks.backend.facade import api as tasks_facade_real

        mock_facade.TaskOriginProduct = tasks_facade_real.TaskOriginProduct
        mock_facade.create_and_run_task.side_effect = _fake
        mock_facade.update_task_run_state.return_value = {}

        await env.run(create_posthog_code_investigation_task, _inputs(team, alert, alert_check))

    # The description (prompt) must reference the previous run id.
    assert str(prev_run_id) in captured_kwargs.get("description", "")


# ---------------------------------------------------------------------------
# get_investigation_run_state
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("run_status", "expected_terminal"),
    [
        ("completed", True),
        ("failed", True),
        ("cancelled", True),
        ("queued", False),
        ("in_progress", False),
    ],
)
async def test_get_investigation_run_state_terminal_statuses(
    env, team, alert, alert_check, run_status, expected_terminal
):
    run_id = uuid.uuid4()
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update)(investigation_task_run_id=run_id)

    run_dto = SimpleNamespace(
        id=run_id,
        status=run_status,
        output={"verdict": "true_positive"} if run_status == "completed" else None,
    )

    with patch.object(_mod, "tasks_facade") as mock_facade:
        mock_facade.get_task_run.return_value = run_dto
        state = await env.run(get_investigation_run_state, _inputs(team, alert, alert_check))

    assert state.terminal is expected_terminal
    assert state.status == run_status


async def test_get_investigation_run_state_returns_output_when_terminal(env, team, alert, alert_check):
    run_id = uuid.uuid4()
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update)(investigation_task_run_id=run_id)
    output = {"verdict": "true_positive", "findings": "f"}
    run_dto = SimpleNamespace(id=run_id, status="completed", output=output)

    with patch.object(_mod, "tasks_facade") as mock_facade:
        mock_facade.get_task_run.return_value = run_dto
        state = await env.run(get_investigation_run_state, _inputs(team, alert, alert_check))

    assert state.terminal is True
    assert state.output == output


# ---------------------------------------------------------------------------
# finalize_posthog_code_investigation
# ---------------------------------------------------------------------------


def _valid_output_dict() -> dict:
    return {
        "findings": "CPU spike detected.",
        "suspected_cause": "Bad deploy.",
        "proposed_mitigation": "Roll back.",
        "confidence": 0.9,
        "verdict": "true_positive",
        "pr_url": None,
    }


@pytest.mark.parametrize(
    ("run_status", "output_sentinel", "expected_investigation_status", "expect_verdict"),
    [
        # Happy path: completed + valid output → DONE with verdict
        ("completed", "valid", InvestigationStatus.DONE, "true_positive"),
        # Run failed → FAILED
        ("failed", None, InvestigationStatus.FAILED, None),
        # Run cancelled → FAILED
        ("cancelled", None, InvestigationStatus.FAILED, None),
        # Completed but schema-invalid output → FAILED
        ("completed", "bad", InvestigationStatus.FAILED, None),
        # Completed but output is None → FAILED
        ("completed", "null", InvestigationStatus.FAILED, None),
    ],
)
async def test_finalize_outcomes(
    env,
    team,
    alert,
    alert_check,
    run_status,
    output_sentinel,
    expected_investigation_status,
    expect_verdict,
):
    run_id = uuid.uuid4()
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update)(investigation_task_run_id=run_id)

    if output_sentinel == "null":
        output = None
    elif output_sentinel == "bad":
        output = {"bad": "data"}
    elif output_sentinel == "valid":
        output = _valid_output_dict()
    else:
        output = None

    run_dto = SimpleNamespace(id=run_id, status=run_status, output=output)

    with patch.object(_mod, "tasks_facade") as mock_facade:
        mock_facade.get_task_run.return_value = run_dto
        await env.run(finalize_posthog_code_investigation, _inputs(team, alert, alert_check))

    await sync_to_async(alert_check.refresh_from_db)()
    assert alert_check.investigation_status == expected_investigation_status

    if expect_verdict:
        assert alert_check.investigation_verdict == expect_verdict
        assert alert_check.investigation_summary is not None
        assert alert_check.investigation_error is None
    else:
        assert alert_check.investigation_error is not None


async def test_finalize_summary_uses_suspected_cause_when_present(env, team, alert, alert_check):
    run_id = uuid.uuid4()
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update)(investigation_task_run_id=run_id)
    output = _valid_output_dict()
    output["suspected_cause"] = "Memory leak in service X."
    output["findings"] = "Something else."

    run_dto = SimpleNamespace(id=run_id, status="completed", output=output)

    with patch.object(_mod, "tasks_facade") as mock_facade:
        mock_facade.get_task_run.return_value = run_dto
        await env.run(finalize_posthog_code_investigation, _inputs(team, alert, alert_check))

    await sync_to_async(alert_check.refresh_from_db)()
    assert "Memory leak in service X." in alert_check.investigation_summary


# ---------------------------------------------------------------------------
# cancel_posthog_code_investigation
# ---------------------------------------------------------------------------


async def test_cancel_sends_facade_cancel_and_writes_failed(env, team, alert, alert_check):
    run_id = uuid.uuid4()
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update)(investigation_task_run_id=run_id)

    with patch.object(_mod, "tasks_facade") as mock_facade:
        mock_facade.send_cancel.return_value = None
        await env.run(cancel_posthog_code_investigation, _inputs(team, alert, alert_check))

    mock_facade.send_cancel.assert_called_once()
    call_args = mock_facade.send_cancel.call_args
    assert str(run_id) in str(call_args)

    await sync_to_async(alert_check.refresh_from_db)()
    assert alert_check.investigation_status == InvestigationStatus.FAILED
    assert "timed out" in alert_check.investigation_error["reason"]


async def test_cancel_still_writes_failed_when_facade_send_cancel_raises(env, team, alert, alert_check):
    run_id = uuid.uuid4()
    await sync_to_async(AlertCheck.objects.filter(id=alert_check.id).update)(investigation_task_run_id=run_id)

    with patch.object(_mod, "tasks_facade") as mock_facade:
        mock_facade.send_cancel.side_effect = RuntimeError("connection refused")
        await env.run(cancel_posthog_code_investigation, _inputs(team, alert, alert_check))

    await sync_to_async(alert_check.refresh_from_db)()
    assert alert_check.investigation_status == InvestigationStatus.FAILED
    assert alert_check.investigation_error is not None
