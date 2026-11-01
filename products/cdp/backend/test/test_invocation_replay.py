from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import Client

from parameterized import parameterized
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    ReadTimeout,
)
from urllib3 import HTTPConnectionPool
from urllib3.exceptions import MaxRetryError, NewConnectionError

from posthog.clickhouse.client.execute import sync_execute

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_invocation_results_sql import INSERT_HOG_INVOCATION_RESULT_SQL
from products.cdp.backend.services.invocation_replay import (
    ReplayCriteria,
    ReplayOverlapError,
    claim_replay,
    execute_replay,
    get_replay_state,
    mark_replay_failed,
    plan_replay,
    release_replay_claim,
    replay_cache,
    start_claimed_send,
)
from products.cdp.backend.tasks.invocation_replay import run_invocation_replay
from products.workflows.backend.facade.models import HogFlow

WINDOW_START = datetime(2026, 10, 22, 11, 30, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
IN_WINDOW = WINDOW_START + timedelta(minutes=30)
EXPIRED = "401: The OAuth token used to make this call expired"
REFUSED = RequestsConnectionError(
    MaxRetryError(HTTPConnectionPool("127.0.0.1"), "/rerun", NewConnectionError(None, "connection refused"))
)
# Minutes after IN_WINDOW that land after the window ends.
RECOVERED = 200


def _invocation_id(suffix: str) -> str:
    return f"018f0000-0000-0000-0000-0000000000{suffix}"


def _row(
    suffix: str,
    status: str,
    minutes: int = 0,
    *,
    first_minutes: int | None = None,
    person: str = "person-1",
    event: str = "",
    error: str = EXPIRED,
    is_retry: int = 0,
    version: int = 1,
) -> dict[str, Any]:
    return {
        "invocation_id": _invocation_id(suffix),
        "status": status,
        "is_retry": is_retry,
        "scheduled_at": IN_WINDOW + timedelta(minutes=minutes),
        # A retry rewrites scheduled_at, while first_scheduled_at keeps the time of the original run.
        "first_scheduled_at": IN_WINDOW + timedelta(minutes=minutes if first_minutes is None else first_minutes),
        "error_kind": "http_4xx" if status == "failed" else "",
        "error_message": error if status == "failed" else "",
        "event_uuid": event,
        "distinct_id": person,
        "person_id": person,
        "version": version,
    }


def _insert(function: HogFunction | HogFlow, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        sync_execute(
            INSERT_HOG_INVOCATION_RESULT_SQL,
            {
                "team_id": function.team_id,
                "function_kind": "hog_flow" if isinstance(function, HogFlow) else "hog_function",
                "function_id": str(function.id),
                "parent_run_id": "",
                "attempts": 1,
                "started_at": row["scheduled_at"],
                "finished_at": row["scheduled_at"],
                "duration_ms": 10,
                "invocation_globals": "{}",
                "is_deleted": 0,
                **row,
            },
        )


def _recovered(person: str = "person-recovered") -> dict[str, Any]:
    # A success after the window proves the integration works again, which the default criteria require.
    return _row("ff", "succeeded", RECOVERED, person=person)


def _criteria(**overrides: Any) -> ReplayCriteria:
    values: dict[str, Any] = {
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "error_message_contains": "401",
        "error_kinds": (),
        "team_ids": (),
        "template_ids": (),
        "exclude_template_ids": (),
        "latest_per_person_template_ids": ("template-hubspot",),
        "require_success_since_window": True,
        "skip_already_rerun": True,
        "skip_failing_before_window": True,
        "include_workflows": False,
        **overrides,
    }
    return ReplayCriteria(**values)


def _function(team: Any, template_id: str, **fields: Any) -> HogFunction:
    return HogFunction.objects.create(
        team=team,
        name=template_id,
        type="destination",
        template_id=template_id,
        hog="",
        **{"enabled": True, **fields},
    )


def _workflow(team: Any, **fields: Any) -> HogFlow:
    hubspot_step = {"id": "sync", "type": "function", "config": {"template_id": "template-hubspot"}}
    return HogFlow.objects.create(
        **{"team": team, "name": "workflow", "status": HogFlow.State.ACTIVE, "actions": [hubspot_step], **fields}
    )


class TestInvocationReplay(ClickhouseTestMixin, APIBaseTest):
    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    @parameterized.expand(
        [
            ("event_destination_failure", "template-google-ads", {}, [_row("a1", "failed")], ["a1"], {}),
            (
                "error_outside_the_filter",
                "template-google-ads",
                {},
                [_row("a1", "failed", error="500: internal error")],
                [],
                None,
            ),
            (
                "later_retry_succeeded_after_the_window",
                "template-google-ads",
                {},
                [_row("a1", "failed"), _row("a1", "succeeded", RECOVERED, first_minutes=0, version=2)],
                [],
                None,
            ),
            (
                "event_delivered_by_a_later_run",
                "template-google-ads",
                {},
                [_row("a1", "failed", event="e1"), _row("a2", "succeeded", 10, event="e1")],
                [],
                {"already_delivered": 1},
            ),
            (
                "already_rerun_and_failed_again",
                "template-google-ads",
                {},
                [_row("a1", "failed", is_retry=1)],
                [],
                {"already_rerun": 1},
            ),
            (
                "person_sync_keeps_only_the_latest_failure",
                "template-hubspot",
                {},
                [_row("a1", "failed", 0), _row("a2", "failed", 10), _row("a3", "failed", 20, person="person-2")],
                ["a2", "a3"],
                {"older_run_for_same_person": 1},
            ),
            (
                "person_sync_superseded_by_a_later_success",
                "template-hubspot",
                {},
                [_row("a1", "failed", 0), _row("a2", "succeeded", 30)],
                [],
                {"superseded_by_later_success": 1},
            ),
            (
                # An older event retried after a newer one succeeded: its scheduled_at
                # is later than the success, its original time is not.
                "person_sync_retried_older_run_is_still_superseded",
                "template-hubspot",
                {},
                [_row("a1", "failed", 40, first_minutes=0), _row("a2", "succeeded", 30)],
                [],
                {"superseded_by_later_success": 1},
            ),
            (
                "person_sync_retried_older_run_is_not_the_latest",
                "template-hubspot",
                {},
                [_row("a1", "failed", 40, first_minutes=0), _row("a2", "failed", 10)],
                ["a2"],
                {"older_run_for_same_person": 1},
            ),
            (
                # One person can update two companies, so company syncs replay every failure.
                "company_sync_is_not_deduplicated_by_person",
                "template-hubspot-company",
                {},
                [_row("a1", "failed", 0), _row("a2", "failed", 10), _row("a3", "succeeded", 30)],
                ["a1", "a2"],
                {},
            ),
            (
                "disabled_function",
                "template-google-ads",
                {"enabled": False},
                [_row("a1", "failed")],
                [],
                {"function_not_replayable": 1},
            ),
        ]
    )
    def test_plans_which_failures_to_replay(
        self,
        _name: str,
        template_id: str,
        function_fields: dict[str, Any],
        rows: list[dict[str, Any]],
        expected_suffixes: list[str],
        expected_skipped: dict[str, int] | None,
    ) -> None:
        function = _function(self.team, template_id, **function_fields)
        _insert(function, [*rows, _recovered()])

        plan = plan_replay(_criteria())

        planned = {f.function_id: f for f in plan.functions}
        if expected_skipped is None:
            assert str(function.id) not in planned
            return
        assert planned[str(function.id)].invocation_ids == tuple(_invocation_id(s) for s in expected_suffixes)
        assert planned[str(function.id)].skipped == expected_skipped

    @parameterized.expand(
        [
            # Later steps can send messages, so a later run for the same person does not cover an earlier one.
            ("replays_every_failed_run", {}, {}, ["a1", "a2"], {}),
            ("only_when_included", {}, {"include_workflows": False}, [], None),
            ("archived", {"status": HogFlow.State.ARCHIVED}, {}, [], {"function_not_replayable": 2}),
            (
                "sensitive_email",
                {"actions": [{"id": "email", "type": "function_email", "config": {"sensitive": True}}]},
                {},
                [],
                {"sends_sensitive_email": 2},
            ),
            ("step_template_excluded", {}, {"exclude_template_ids": ("template-hubspot",)}, [], None),
            ("step_template_not_selected", {}, {"template_ids": ("template-google-ads",)}, [], None),
        ]
    )
    def test_plans_which_workflow_failures_to_replay(
        self,
        _name: str,
        workflow_fields: dict[str, Any],
        criteria: dict[str, Any],
        expected_suffixes: list[str],
        expected_skipped: dict[str, int] | None,
    ) -> None:
        workflow = _workflow(self.team, **workflow_fields)
        _insert(workflow, [_row("a1", "failed", 0), _row("a2", "failed", 10), _recovered()])

        plan = plan_replay(_criteria(**{"include_workflows": True, **criteria}))

        planned = {f.function_id: f for f in plan.functions}
        if expected_skipped is None:
            assert str(workflow.id) not in planned
            return
        assert planned[str(workflow.id)].invocation_ids == tuple(_invocation_id(s) for s in expected_suffixes)
        assert planned[str(workflow.id)].skipped == expected_skipped

    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_sends_workflow_runs_to_the_workflow_rerun(self, rerun: MagicMock) -> None:
        rerun.return_value = MagicMock(status_code=200, text="{}")
        function = _function(self.team, "template-google-ads")
        workflow = _workflow(self.team)
        for target in (function, workflow):
            _insert(target, [_row("a1", "failed"), _recovered()])

        execute_replay(plan_replay(_criteria(include_workflows=True)), actor="test")

        sent = {(call.kwargs["function_kind"], call.kwargs["function_id"]) for call in rerun.call_args_list}
        assert sent == {("hog_function", str(function.id)), ("hog_flow", str(workflow.id))}

    @parameterized.expand(
        [
            ("require_success_since_window", [_row("a1", "failed")], "no_success_since_window"),
            (
                "skip_failing_before_window",
                [_row("b1", "failed", -6 * 60), _row("a1", "failed"), _recovered()],
                "failing_before_window",
            ),
        ]
    )
    def test_holds_functions_whose_failures_have_another_cause(
        self, option: str, rows: list[dict[str, Any]], reason: str
    ) -> None:
        function = _function(self.team, "template-google-ads")
        _insert(function, rows)

        assert plan_replay(_criteria()).functions[0].skipped == {reason: 1}
        assert plan_replay(_criteria(**{option: False})).invocation_count == 1

    @patch("products.cdp.backend.services.invocation_replay.HOG_INVOCATION_RERUN_MAX_COUNT", 1)
    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_task_sends_the_reviewed_plan_by_id_and_refuses_a_changed_one(self, rerun: MagicMock) -> None:
        rerun.return_value = MagicMock(status_code=200, text="{}")
        function = _function(self.team, "template-google-ads")
        _insert(function, [_row("a1", "failed"), _row("a2", "failed", 5), _recovered()])
        criteria = _criteria()
        plan = plan_replay(criteria)
        reviewed = plan_replay(_criteria(window_end=IN_WINDOW + timedelta(minutes=1)))

        claim = claim_replay(reviewed, actor="test")
        assert claim
        run_invocation_replay(_criteria().to_payload(), reviewed.fingerprint, "test", claim)
        assert (get_replay_state(reviewed.fingerprint) or {})["status"] == "refused"
        rerun.assert_not_called()

        claim = claim_replay(plan, actor="test")
        assert claim
        run_invocation_replay(criteria.to_payload(), plan.fingerprint, "test", claim)

        sent = [call.kwargs["payload"]["filter"]["invocation_ids"] for call in rerun.call_args_list]
        assert sent == [[_invocation_id("a1")], [_invocation_id("a2")]]
        state = get_replay_state(plan.fingerprint) or {}
        assert (state["status"], state["failed_requests"], len(state["results"])) == ("done", 0, 2)

    def test_a_plan_can_be_claimed_once(self) -> None:
        function = _function(self.team, "template-google-ads")
        _insert(function, [_row("a1", "failed"), _recovered()])
        plan = plan_replay(_criteria())

        with patch.object(replay_cache, "set", side_effect=ConnectionError("redis down")):
            with self.assertRaises(ConnectionError):
                claim_replay(plan, actor="first")
        assert claim_replay(plan, actor="first")
        assert not claim_replay(plan, actor="second")
        assert (get_replay_state(plan.fingerprint) or {})["actor"] == "first"

    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_records_a_failed_request_and_continues(self, rerun: MagicMock) -> None:
        rerun.side_effect = [ConnectionError("cdp api down"), MagicMock(status_code=200, text="{}")]
        for template_id in ("template-google-ads", "template-snapchat-ads"):
            _insert(_function(self.team, template_id), [_row("a1", "failed"), _recovered()])
        plan = plan_replay(_criteria())

        results = execute_replay(plan, actor="test")

        assert sorted(r.status_code for r in results) == [0, 200]
        assert (get_replay_state(plan.fingerprint) or {})["failed_requests"] == 1

    @parameterized.expand(
        [
            ("connection_refused", "send", REFUSED, True),
            ("rejected_by_cdp_api", "send", MagicMock(status_code=400, text="{}"), True),
            ("gateway_error_response", "send", MagicMock(status_code=504, text="{}"), False),
            ("planning_failed_in_task", "plan", RuntimeError("clickhouse down"), True),
            ("read_timeout", "send", ReadTimeout("read timed out"), False),
            ("interrupted_during_a_request", "send", KeyboardInterrupt(), False),
        ]
    )
    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_a_send_can_be_sent_again_only_when_it_surely_queued_nothing(
        self, _name: str, stage: str, outcome: Any, can_resend: bool, rerun: MagicMock
    ) -> None:
        if isinstance(outcome, BaseException):
            rerun.side_effect = outcome
        else:
            rerun.return_value = outcome
        _insert(_function(self.team, "template-google-ads"), [_row("a1", "failed"), _recovered()])
        criteria = _criteria()
        plan = plan_replay(criteria)
        claim = claim_replay(plan, actor="first")
        assert claim

        with patch(
            "products.cdp.backend.tasks.invocation_replay.plan_replay",
            side_effect=outcome if stage == "plan" else plan_replay,
        ):
            try:
                run_invocation_replay(criteria.to_payload(), plan.fingerprint, "first", claim)
            except BaseException as raised:
                assert raised is outcome

        assert (claim_replay(plan, actor="second") is not None) is can_resend

    @parameterized.expand(
        [
            ("rejected_by_cdp_api", MagicMock(status_code=400, text="{}"), True),
            ("read_timeout", ReadTimeout("read timed out"), False),
        ]
    )
    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_an_overlapping_plan_waits_until_the_first_surely_queued_nothing(
        self, _name: str, outcome: Any, frees_destination: bool, rerun: MagicMock
    ) -> None:
        if isinstance(outcome, BaseException):
            rerun.side_effect = outcome
        else:
            rerun.return_value = outcome
        _insert(
            _function(self.team, "template-google-ads"), [_row("a1", "failed"), _row("a2", "failed", 60), _recovered()]
        )
        first = plan_replay(_criteria(window_end=IN_WINDOW + timedelta(minutes=30)))
        overlapping = plan_replay(_criteria())
        assert (first.invocation_count, overlapping.invocation_count) == (1, 2)
        with time_machine.travel("2026-10-23T08:00:00Z", tick=False):
            assert claim_replay(first, actor="first")
        with time_machine.travel("2026-10-23T10:00:00Z", tick=False):
            with self.assertRaises(ReplayOverlapError):
                claim_replay(overlapping, actor="second")
            execute_replay(first, actor="first")

        with time_machine.travel("2026-10-23T12:00:00Z", tick=False):
            if frees_destination:
                assert claim_replay(overlapping, actor="second")
            else:
                with self.assertRaises(ReplayOverlapError):
                    claim_replay(overlapping, actor="second")

    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_staff_can_release_a_send_only_once_its_worker_stopped_reporting(self, rerun: MagicMock) -> None:
        rerun.return_value = MagicMock(status_code=200, text="{}")
        _insert(_function(self.team, "template-google-ads"), [_row("a1", "failed"), _recovered()])
        criteria = _criteria()
        plan = plan_replay(criteria)
        with time_machine.travel("2026-10-23T07:00:00Z", tick=False):
            planning = claim_replay(plan, actor="first")
            assert planning
        with time_machine.travel("2026-10-23T07:20:00Z", tick=False):
            assert start_claimed_send(plan.fingerprint, planning)
            assert not release_replay_claim(plan.fingerprint, actor="staff")
            mark_replay_failed(plan.fingerprint, "test reset")
        with time_machine.travel("2026-10-23T08:00:00Z", tick=False):
            stalled = claim_replay(plan, actor="first")
            assert stalled
            assert not release_replay_claim(plan.fingerprint, actor="staff")
        with time_machine.travel("2026-10-23T08:20:00Z", tick=False):
            assert release_replay_claim(plan.fingerprint, actor="staff")
            resend = claim_replay(plan, actor="second")
            assert resend

            # The stalled task can still start late. Only the resend sends, and only once.
            for claim in (stalled, resend, resend):
                run_invocation_replay(criteria.to_payload(), plan.fingerprint, "staff", claim)
        assert rerun.call_count == 1


class TestReplayAdmin(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.function = _function(self.team, "template-google-ads")
        _insert(self.function, [_row("a1", "failed"), _row("a2", "failed", 5), _recovered()])
        self.form = {
            "window_start": "2026-10-22 11:30:00",
            "window_end": "2026-10-22 14:00:00",
            "error_message_contains": "401",
            "latest_per_person_template_ids": "template-hubspot",
            "require_success_since_window": "True",
            "skip_already_rerun": "True",
            "skip_failing_before_window": "True",
        }
        self.url = "/admin/cdp/hogfunction/replay-failed-invocations/"
        self.admin_client = Client()
        self.admin_client.force_login(self.user)

    def tearDown(self) -> None:
        cache.clear()
        super().tearDown()

    def _fingerprint(self) -> str:
        return self.admin_client.post(self.url, {**self.form, "action": "details"}).context["plan"].fingerprint

    @parameterized.expand(
        [
            ("stale_fingerprint", "0000000000000000", "2"),
            ("wrong_confirmation_count", None, "3"),
        ]
    )
    @patch("products.cdp.backend.admin.hog_function_admin.run_invocation_replay")
    def test_send_refuses_without_a_matching_review(
        self, _name: str, fingerprint: str | None, confirm: str, task: MagicMock
    ) -> None:
        response = self.admin_client.post(
            self.url,
            {
                **self.form,
                "action": "execute",
                "fingerprint": fingerprint or self._fingerprint(),
                "confirm_count": confirm,
            },
        )

        assert response.status_code == 200
        assert response.context["step"] == "details"
        task.delay.assert_not_called()

    @patch("products.cdp.backend.admin.hog_function_admin.run_invocation_replay")
    def test_send_dispatches_the_reviewed_plan_once(self, task: MagicMock) -> None:
        fingerprint = self._fingerprint()
        send = {**self.form, "action": "execute", "fingerprint": fingerprint, "confirm_count": "2"}

        first = self.admin_client.post(self.url, send)
        second = self.admin_client.post(self.url, send)

        assert first.status_code == second.status_code == 302
        assert first["Location"].endswith(f"/replay-failed-invocations/{fingerprint}/")
        task.delay.assert_called_once()
        assert task.delay.call_args.args[1] == fingerprint
        status = self.admin_client.get(first["Location"])
        assert status.context["state"]["status"] == "queued"

    @patch("products.cdp.backend.admin.hog_function_admin.run_invocation_replay")
    def test_a_send_whose_task_may_have_been_queued_stays_blocked_until_released(self, task: MagicMock) -> None:
        task.delay.side_effect = [ConnectionError("broker down"), None]
        fingerprint = self._fingerprint()
        send = {**self.form, "action": "execute", "fingerprint": fingerprint, "confirm_count": "2"}

        first = self.admin_client.post(self.url, send)
        status = self.admin_client.get(first["Location"])
        assert (status.context["state"]["status"], status.context["can_release"]) == ("failed", True)

        self.admin_client.post(self.url, send)
        assert task.delay.call_count == 1

        self.admin_client.post(first["Location"], {"action": "release"})
        self.admin_client.post(self.url, send)
        assert task.delay.call_count == 2

    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_staff_can_allow_a_resend_after_an_uncertain_send(self, rerun: MagicMock) -> None:
        rerun.side_effect = ReadTimeout("read timed out")
        plan = plan_replay(_criteria())
        assert claim_replay(plan, actor="first")
        execute_replay(plan, actor="first")
        status_url = f"{self.url}{plan.fingerprint}/"
        assert not claim_replay(plan, actor="second")
        assert self.admin_client.get(status_url).context["can_release"]

        self.admin_client.post(status_url, {"action": "release"})

        assert claim_replay(plan, actor="second")
