from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import Client

from parameterized import parameterized

from posthog.clickhouse.client.execute import sync_execute

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.hog_invocation_results_sql import INSERT_HOG_INVOCATION_RESULT_SQL
from products.cdp.backend.services.invocation_replay import ReplayCriteria, plan_replay

WINDOW_START = datetime(2026, 10, 22, 11, 30, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
IN_WINDOW = WINDOW_START + timedelta(minutes=30)
AFTER_WINDOW = WINDOW_END + timedelta(hours=1)
EXPIRED = "401: The OAuth token used to make this call expired"

# (invocation suffix, status, minutes after IN_WINDOW, person, event, error message, is_retry, version)
Row = tuple[str, str, int, str, str, str, int, int]


def _row(
    suffix: str,
    status: str,
    minutes: int = 0,
    *,
    person: str = "person-1",
    event: str = "",
    error: str = EXPIRED,
    is_retry: int = 0,
    version: int = 1,
) -> Row:
    return (suffix, status, minutes, person, event, error if status == "failed" else "", is_retry, version)


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
        **overrides,
    }
    return ReplayCriteria(**values)


def _insert(function: HogFunction, rows: list[Row]) -> None:
    for suffix, status, minutes, person, event, error, is_retry, version in rows:
        scheduled_at = IN_WINDOW + timedelta(minutes=minutes)
        sync_execute(
            INSERT_HOG_INVOCATION_RESULT_SQL,
            {
                "team_id": function.team_id,
                "function_kind": "hog_function",
                "function_id": str(function.id),
                "invocation_id": f"018f0000-0000-0000-0000-0000000000{suffix}",
                "parent_run_id": "",
                "status": status,
                "attempts": 1,
                "is_retry": is_retry,
                "scheduled_at": scheduled_at,
                "first_scheduled_at": scheduled_at,
                "started_at": scheduled_at,
                "finished_at": scheduled_at,
                "duration_ms": 10,
                "error_kind": "http_4xx" if status == "failed" else "",
                "error_message": error,
                "event_uuid": event,
                "distinct_id": person,
                "person_id": person,
                "invocation_globals": "{}",
                "version": version,
                "is_deleted": 0,
            },
        )


class TestInvocationReplay(ClickhouseTestMixin, APIBaseTest):
    def _function(self, template_id: str, **fields: Any) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name=template_id,
            type="destination",
            template_id=template_id,
            hog="",
            **{"enabled": True, **fields},
        )

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
                [_row("a1", "failed"), ("a1", "succeeded", 200, "person-1", "", "", 0, 2)],
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
        rows: list[Row],
        expected_suffixes: list[str],
        expected_skipped: dict[str, int] | None,
    ) -> None:
        function = self._function(template_id, **function_fields)
        # A success after the window proves the integration works again, which the default criteria require.
        _insert(function, [*rows, _row("ff", "succeeded", 200, person="person-recovered")])

        plan = plan_replay(_criteria())

        planned = {f.function_id: f for f in plan.functions}
        if expected_skipped is None:
            assert str(function.id) not in planned
            return
        assert planned[str(function.id)].invocation_ids == tuple(
            f"018f0000-0000-0000-0000-0000000000{suffix}" for suffix in expected_suffixes
        )
        assert planned[str(function.id)].skipped == expected_skipped

    def test_holds_a_function_that_has_not_succeeded_since_the_window(self) -> None:
        function = self._function("template-google-ads")
        _insert(function, [_row("a1", "failed")])

        assert plan_replay(_criteria()).functions[0].skipped == {"no_success_since_window": 1}
        assert plan_replay(_criteria(require_success_since_window=False)).invocation_count == 1


class TestReplayAdmin(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.function = HogFunction.objects.create(
            team=self.team, name="Ads", type="destination", template_id="template-google-ads", hog="", enabled=True
        )
        _insert(self.function, [_row("a1", "failed"), _row("a2", "failed", 5), _row("ff", "succeeded", 200)])
        self.form = {
            "window_start": "2026-10-22 11:30:00",
            "window_end": "2026-10-22 14:00:00",
            "error_message_contains": "401",
            "latest_per_person_template_ids": "template-hubspot",
            "require_success_since_window": "True",
            "skip_already_rerun": "True",
        }
        self.url = "/admin/cdp/hogfunction/replay-failed-invocations/"
        self.admin_client = Client()
        self.admin_client.force_login(self.user)

    @parameterized.expand(
        [
            ("stale_fingerprint", "0000000000000000", "2"),
            ("wrong_confirmation_count", None, "3"),
        ]
    )
    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_send_refuses_without_a_matching_review(
        self, _name: str, fingerprint: str | None, confirm: str, rerun: MagicMock
    ) -> None:
        preview = self.admin_client.post(self.url, {**self.form, "action": "details"})
        assert preview.status_code == 200
        plan_fingerprint = preview.context["plan"].fingerprint

        response = self.admin_client.post(
            self.url,
            {
                **self.form,
                "action": "execute",
                "fingerprint": fingerprint or plan_fingerprint,
                "confirm_count": confirm,
            },
        )

        assert response.status_code == 200
        assert response.context["step"] == "details"
        rerun.assert_not_called()

    @patch("products.cdp.backend.services.invocation_replay.HOG_INVOCATION_RERUN_MAX_COUNT", 1)
    @patch("products.cdp.backend.services.invocation_replay.rerun_hog_invocations")
    def test_send_queues_the_reviewed_invocations_by_id(self, rerun: MagicMock) -> None:
        rerun.return_value = MagicMock(status_code=200, text="{}")
        summary = self.admin_client.post(self.url, {**self.form, "action": "preview"})
        assert summary.context["step"] == "summary"
        assert summary.context["plan"].invocation_count == 2

        response = self.admin_client.post(
            self.url,
            {
                **self.form,
                "action": "execute",
                "fingerprint": summary.context["plan"].fingerprint,
                "confirm_count": "2",
            },
        )

        assert response.context["step"] == "results"
        sent = [call.kwargs["payload"]["filter"]["invocation_ids"] for call in rerun.call_args_list]
        assert sent == [["018f0000-0000-0000-0000-0000000000a1"], ["018f0000-0000-0000-0000-0000000000a2"]]
        assert {call.kwargs["function_id"] for call in rerun.call_args_list} == {str(self.function.id)}
