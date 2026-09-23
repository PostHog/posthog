from datetime import UTC, datetime, timedelta, timezone
from itertools import product

import time_machine
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.tasks import usage_report
from posthog.usage_counters import (
    COUNTER_FLAG_NAMES,
    SHADOW_FAILURES,
    UsageCounter,
    UsageCounterCaller,
    UsageCounterMode,
    UsageCounterService,
    UsageRecordTotal,
    _mode_cache,
    resolve_modes,
    validate_usage_record_window,
)
from posthog.utils import DayRange


class TestUsageCounterReport(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        _mode_cache.clear()
        self.addCleanup(_mode_cache.clear)
        self.legacy = {counter: Mock(return_value=[]) for counter in UsageCounter}
        self.records = Mock(return_value=[])
        self.exceptions = Mock(side_effect=lambda begin, end: ({}, self.legacy[UsageCounter.EXCEPTIONS](begin, end)))
        self.events = Mock(side_effect=lambda begin, end, **kwargs: self.legacy[UsageCounter.EVENTS](begin, end))
        self.logs_retention = Mock(
            side_effect=lambda begin, end: {"30d": self.legacy[UsageCounter.LOGS_RETENTION_30D_BYTES](begin, end)}
        )
        patches = {
            "get_teams_with_logs_retention_bytes_in_period": self.logs_retention,
            "get_teams_with_rows_synced_in_period": self.legacy[UsageCounter.ROWS_SYNCED],
            "get_teams_with_free_historical_rows_synced_in_period": self.legacy[
                UsageCounter.FREE_HISTORICAL_ROWS_SYNCED
            ],
            "get_teams_with_rows_exported_in_period": self.legacy[UsageCounter.ROWS_EXPORTED],
            "get_teams_with_logs_bytes_in_period": self.legacy[UsageCounter.LOGS_BYTES],
            "get_teams_with_ai_credits_used_in_period": self.legacy[UsageCounter.AI_CREDITS],
            "get_teams_with_signals_credits_used_in_period": self.legacy[UsageCounter.SIGNALS_CREDITS],
            "get_teams_with_posthog_code_credits_used_in_period": self.legacy[UsageCounter.POSTHOG_CODE_CREDITS],
            "get_teams_with_replay_vision_credits_used_in_period": self.legacy[UsageCounter.REPLAY_VISION_CREDITS],
            "get_teams_with_billable_event_count_in_period": self.events,
            "get_teams_with_billable_enhanced_persons_event_count_in_period": Mock(
                side_effect=lambda begin, end, **kwargs: self.legacy[UsageCounter.ENHANCED_PERSON_EVENTS](begin, end)
            ),
            "get_teams_with_recording_count_in_period": Mock(
                side_effect=lambda begin, end, snapshot_source: self.legacy[
                    UsageCounter.RECORDINGS if snapshot_source == "web" else UsageCounter.MOBILE_RECORDINGS
                ](begin, end)
            ),
            "get_teams_with_mobile_billable_recording_count_in_period": self.legacy[
                UsageCounter.MOBILE_BILLABLE_RECORDINGS
            ],
            "get_teams_with_survey_responses_count_in_period": self.legacy[UsageCounter.SURVEY_RESPONSES],
            "get_teams_with_ai_event_count_in_period": self.legacy[UsageCounter.AI_EVENTS],
            "get_teams_with_exceptions_captured_in_period": self.exceptions,
            "get_teams_with_cdp_billable_invocations_in_period": self.legacy[UsageCounter.CDP_INVOCATIONS],
            "get_teams_with_feature_flag_requests_count_in_period": Mock(
                side_effect=lambda begin, end, kind: self.legacy[
                    UsageCounter.FEATURE_FLAG_REQUESTS
                    if kind == usage_report.FlagRequestType.DECIDE
                    else UsageCounter.FEATURE_FLAG_LOCAL_EVALUATION_REQUESTS
                ](begin, end)
            ),
            "get_teams_with_workflow_emails_sent_in_period": self.legacy[UsageCounter.WORKFLOW_EMAILS],
            "get_teams_with_workflow_push_sent_in_period": self.legacy[UsageCounter.WORKFLOW_PUSH],
            "get_teams_with_workflow_sms_sent_in_period": self.legacy[UsageCounter.WORKFLOW_SMS],
            "get_teams_with_workflow_billable_invocations_in_period": self.legacy[UsageCounter.WORKFLOW_INVOCATIONS],
            "get_usage_records_in_period": self.records,
        }
        patcher = patch.multiple(usage_report, **patches)
        patcher.start()
        self.addCleanup(patcher.stop)

    @parameterized.expand([("counts", False, False), ("zero", True, False), ("comparison_failure", False, True)])
    @override_settings(USAGE_COUNTER_REALTIME_MODES="")
    def test_fetch_report_uses_resolved_plan_and_preserves_legacy_counts(
        self, _name: str, empty: bool, fails: bool
    ) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        rows = (
            []
            if empty
            else [
                UsageRecordTotal(team_id=1, organization_id="org-a", usage_key="cdp_billable_invocations", quantity=4),
                UsageRecordTotal(team_id=2, organization_id="org-a", usage_key="cdp_billable_invocations", quantity=5),
            ]
        )
        records_query = self.records
        records_query.return_value = rows
        records_query.side_effect = RuntimeError("unavailable") if fails else None
        legacy_query = self.legacy[UsageCounter.CDP_INVOCATIONS]
        legacy_query.return_value = [(1, 12)]
        email_query = self.legacy[UsageCounter.WORKFLOW_EMAILS]
        email_query.return_value = [(1, 3)]
        service = UsageCounterService()
        failures_before = SHADOW_FAILURES.labels(caller="daily_report", stage="scan")._value.get()
        with patch(
            "posthoganalytics.get_feature_flag",
            side_effect=lambda name, distinct_id: "both" if name.endswith("cdp-invocations") else "legacy",
        ) as flag:
            plan = service.resolve_plan(period, caller="daily_report")
            flag.side_effect = None
            flag.return_value = "legacy"
            report = service.fetch_report(period, plan=plan)
            assert flag.call_count == len(COUNTER_FLAG_NAMES)

        assert report.counts == {
            **{counter.value: [] for counter in UsageCounter},
            UsageCounter.CDP_INVOCATIONS.value: [(1, 12)],
            UsageCounter.WORKFLOW_EMAILS.value: [(1, 3)],
        }
        assert report.usage_sources == {
            **{counter.value.removeprefix("teams_with_"): "legacy" for counter in UsageCounter},
            "cdp_billable_invocations_in_period": "both",
        }
        assert report.realtime_counters == (
            None if fails else {"cdp_billable_invocations_in_period": {} if empty else {"org-a": 9}}
        )
        records_query.assert_called_once_with(period, ("cdp_billable_invocations",), "daily_report")
        legacy_query.assert_called_once_with(period.start, period.end)
        email_query.assert_called_once_with(period.start, period.end)
        assert SHADOW_FAILURES.labels(caller="daily_report", stage="scan")._value.get() == failures_before + int(fails)
        with self.assertRaisesRegex(ValueError, "across periods"):
            service.fetch_report(
                DayRange(start=period.start + timedelta(days=1), end=period.end + timedelta(days=1)), plan=plan
            )

    @override_settings(USAGE_COUNTER_REALTIME_MODES="")
    def test_legacy_report_without_plan_does_not_query_records(self) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        self.records.side_effect = AssertionError("unexpected scan")
        self.legacy[UsageCounter.CDP_INVOCATIONS].return_value = [(1, 12)]
        with patch("posthoganalytics.get_feature_flag") as flag:
            report = UsageCounterService().fetch_report(period)
        assert report.counts[UsageCounter.CDP_INVOCATIONS.value] == [(1, 12)]
        assert report.usage_sources is None
        assert report.realtime_counters is None
        self.records.assert_not_called()
        flag.assert_not_called()

    @parameterized.expand([("legacy",), ("both",)])
    def test_authoritative_query_failure_fails_report(self, mode: str) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        self.legacy[UsageCounter.CDP_INVOCATIONS].side_effect = RuntimeError("legacy unavailable")
        service = UsageCounterService()
        with (
            self.settings(USAGE_COUNTER_REALTIME_MODES=f"cdp-invocations:{mode}"),
            patch("posthoganalytics.get_feature_flag", return_value="legacy"),
        ):
            plan = service.resolve_plan(period, caller="daily_report")
        with self.assertRaisesRegex(RuntimeError, "legacy unavailable"):
            service.fetch_report(period, plan=plan)

    @parameterized.expand(
        [
            ("cross_midnight", 25, UTC),
            ("offset_crosses_utc_midnight", 24, timezone(timedelta(hours=-5))),
            ("naive", 24, None),
            ("empty", 0, UTC),
        ]
    )
    def test_rejects_invalid_scan_windows(self, _name: str, hours: int, tz: timezone | None) -> None:
        start = datetime(2026, 5, 4, tzinfo=tz)
        with self.assertRaises(ValueError):
            validate_usage_record_window(DayRange(start=start, end=start + timedelta(hours=hours)))

    @parameterized.expand(
        [(None,), (False,), (True,), ("legacy",), ("both",), ("realtime",), ("invalid",), (RuntimeError("offline"),)]
    )
    @override_settings(USAGE_COUNTER_REALTIME_MODES="")
    def test_flag_selects_query_mode_or_defaults_to_legacy(self, flag_value: str | bool | None | Exception) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        records_query = self.records
        records_query.return_value = [
            UsageRecordTotal(team_id=1, organization_id="org-a", usage_key="cdp_billable_invocations", quantity=9)
        ]
        self.legacy[UsageCounter.CDP_INVOCATIONS].return_value = [(1, 12)]
        service = UsageCounterService()
        with patch(
            "posthoganalytics.get_feature_flag",
            side_effect=lambda name, distinct_id: flag_value if name.endswith("cdp-invocations") else "legacy",
        ) as flag:
            if isinstance(flag_value, Exception):
                flag.side_effect = flag_value
            plan = service.resolve_plan(period, caller="daily_report")
            report = service.fetch_report(period, plan=plan)
            assert report.counts[UsageCounter.CDP_INVOCATIONS.value] == [(1, 9 if flag_value == "realtime" else 12)]
            assert (report.realtime_counters is not None) == (flag_value == "both")
            assert records_query.call_count == int(flag_value in ("both", "realtime"))
            assert flag.call_count == len(COUNTER_FLAG_NAMES)

    @parameterized.expand([("both", True), ("legacy", False), ("unknown", False)])
    def test_local_override_does_not_consult_flag_service(self, mode: str, enabled: bool) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        service = UsageCounterService()
        with (
            self.settings(USAGE_COUNTER_REALTIME_MODES=f"cdp-invocations:{mode}"),
            patch("posthoganalytics.get_feature_flag") as flag,
        ):
            plan = service.resolve_plan(period, caller="daily_report")
            assert (service.fetch_report(period, plan=plan).realtime_counters is not None) == enabled
            assert all(call.args[0] != "usage-counter-realtime-cdp-invocations" for call in flag.call_args_list)

    @parameterized.expand(
        list(product(UsageCounterMode, ("daily_report", "usage_reports_v2", "quota_limiting"), (0, 1)))
    )
    @time_machine.travel("2026-05-04T12:00:00Z", tick=False)
    def test_mode_selects_queries_for_every_caller_and_day(
        self, mode: UsageCounterMode, caller: UsageCounterCaller, days_ago: int
    ) -> None:
        start = datetime(2026, 5, 4, tzinfo=UTC) - timedelta(days=days_ago)
        period = DayRange(start=start, end=start + timedelta(days=1))
        legacy = self.legacy[UsageCounter.CDP_INVOCATIONS]
        legacy.return_value = [(1, 12)]
        records = self.records
        records.return_value = [
            UsageRecordTotal(team_id=1, organization_id="org-a", usage_key="cdp_billable_invocations", quantity=9)
        ]
        service = UsageCounterService()
        with (
            self.settings(USAGE_COUNTER_REALTIME_MODES=f"cdp-invocations:{mode}"),
            patch("posthoganalytics.get_feature_flag", return_value="legacy"),
        ):
            plan = service.resolve_plan(period, caller=caller)
        report = service.fetch_report(period, plan=plan)
        assert set(report.counts) == {counter.value for counter in UsageCounter}
        assert report.counts[UsageCounter.CDP_INVOCATIONS.value] == [
            (1, 9 if mode == UsageCounterMode.REALTIME else 12)
        ]
        assert legacy.call_count == int(mode != UsageCounterMode.REALTIME)
        assert records.call_count == int(mode != UsageCounterMode.LEGACY)
        assert report.realtime_counters == (
            {"cdp_billable_invocations_in_period": {"org-a": 9}} if mode == UsageCounterMode.BOTH else None
        )
        if mode == UsageCounterMode.REALTIME:
            records.side_effect = RuntimeError("records unavailable")
            with self.assertRaisesRegex(RuntimeError, "records unavailable"):
                service.fetch_report(period, plan=plan)

    @override_settings(USAGE_COUNTER_REALTIME_MODES="")
    def test_mode_cache_expires_without_changing_existing_plan(self) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        service = UsageCounterService()
        with (
            patch("posthog.usage_counters.time.monotonic", return_value=100) as clock,
            patch("posthoganalytics.get_feature_flag", return_value="both") as flag,
        ):
            modes = resolve_modes("daily_report")
            assert modes == {
                counter: UsageCounterMode.BOTH if counter in COUNTER_FLAG_NAMES else UsageCounterMode.LEGACY
                for counter in UsageCounter
            }
            plan = service.resolve_plan(period, caller="daily_report")
            flag.return_value = "realtime"
            assert resolve_modes("usage_reports_v2") == modes
            assert resolve_modes("quota_limiting") == modes
            assert flag.call_count == len(COUNTER_FLAG_NAMES)
            clock.return_value = 161
            assert resolve_modes("daily_report") == {
                counter: UsageCounterMode.REALTIME if counter in COUNTER_FLAG_NAMES else UsageCounterMode.LEGACY
                for counter in UsageCounter
            }
            assert flag.call_count == 2 * len(COUNTER_FLAG_NAMES)
            with self.settings(USAGE_COUNTER_REALTIME_MODES="cdp-invocations:legacy"):
                assert resolve_modes("daily_report")[UsageCounter.CDP_INVOCATIONS] == UsageCounterMode.LEGACY
            report = service.fetch_report(period, plan=plan)
            assert report.counts[UsageCounter.CDP_INVOCATIONS.value] == []
            assert report.realtime_counters == {
                counter.value.removeprefix("teams_with_"): {} for counter in COUNTER_FLAG_NAMES
            }

    @parameterized.expand([(False,), (True,)])
    def test_mixed_sources_share_one_scan_and_preserve_authoritative_failure(self, fails: bool) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        cdp_legacy = self.legacy[UsageCounter.CDP_INVOCATIONS]
        cdp_legacy.return_value = [(1, 12)]
        email_legacy = self.legacy[UsageCounter.WORKFLOW_EMAILS]
        email_legacy.side_effect = AssertionError("unexpected legacy email query")
        records = self.records
        records.return_value = [
            UsageRecordTotal(team_id=1, organization_id="org-a", usage_key="cdp_billable_invocations", quantity=9),
            UsageRecordTotal(team_id=1, organization_id="org-a", usage_key="workflow_emails_sent", quantity=3),
        ]
        records.side_effect = RuntimeError("records unavailable") if fails else None
        service = UsageCounterService()
        with (
            self.settings(USAGE_COUNTER_REALTIME_MODES="cdp-invocations:both,workflow-emails:realtime"),
            patch("posthoganalytics.get_feature_flag", return_value="legacy"),
        ):
            plan = service.resolve_plan(period, caller="daily_report")
        if fails:
            with self.assertRaisesRegex(RuntimeError, "records unavailable"):
                service.fetch_report(period, plan=plan)
        else:
            report = service.fetch_report(period, plan=plan)
            assert report.counts[UsageCounter.CDP_INVOCATIONS.value] == [(1, 12)]
            assert report.counts[UsageCounter.WORKFLOW_EMAILS.value] == [(1, 3)]
            assert report.realtime_counters == {"cdp_billable_invocations_in_period": {"org-a": 9}}
        records.assert_called_once_with(period, ("cdp_billable_invocations", "workflow_emails_sent"), "daily_report")
        email_legacy.assert_not_called()

    @parameterized.expand([(mode,) for mode in UsageCounterMode])
    def test_remaining_readers_preserve_counts_and_exception_breakdowns(self, mode: UsageCounterMode) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        counter_keys = {
            UsageCounter.EVENTS: ("events", 101),
            UsageCounter.ENHANCED_PERSON_EVENTS: ("enhanced_person_events", 102),
            UsageCounter.RECORDINGS: ("session_replay_recordings", 103),
            UsageCounter.MOBILE_RECORDINGS: ("mobile_replay_recordings", 104),
            UsageCounter.MOBILE_BILLABLE_RECORDINGS: ("mobile_replay_recordings", 104),
            UsageCounter.SURVEY_RESPONSES: ("survey_responses", 105),
            UsageCounter.AI_EVENTS: ("ai_events", 106),
            UsageCounter.EXCEPTIONS: ("exceptions", 107),
        }
        for index, counter in enumerate(counter_keys):
            self.legacy[counter].return_value = [(1, index + 1)]
        self.exceptions.side_effect = None
        self.exceptions.return_value = ({"web": [[1, 3]], "web_lite": [[1, 5]]}, [[1, 8]])
        self.records.return_value = [
            UsageRecordTotal(team_id=1, organization_id="org-a", usage_key=key, quantity=quantity)
            for key, quantity in dict(counter_keys.values()).items()
        ]
        with patch("posthoganalytics.get_feature_flag", return_value=mode):
            service = UsageCounterService()
            plan = service.resolve_plan(period, caller="daily_report", counters=tuple(counter_keys))
        report = service.fetch_report(period, plan=plan)

        for index, (counter, (_, quantity)) in enumerate(counter_keys.items()):
            assert report.counts[counter] == [(1, quantity if mode == UsageCounterMode.REALTIME else index + 1)]
        assert report.counts["teams_with_web_exceptions_captured_in_period"] == [(1, 3)]
        assert report.counts["teams_with_js_lite_exceptions_captured_in_period"] == [(1, 5)]
        self.exceptions.assert_called_once_with(period.start, period.end)
        self.legacy[UsageCounter.CDP_INVOCATIONS].assert_not_called()
        if mode == UsageCounterMode.LEGACY:
            self.records.assert_not_called()
            assert report.realtime_counters is None
        else:
            self.records.assert_called_once_with(period, tuple(dict(counter_keys.values())), "daily_report")
            assert report.realtime_counters == (
                {
                    counter.value.removeprefix("teams_with_"): {"org-a": quantity}
                    for counter, (_, quantity) in counter_keys.items()
                }
                if mode == UsageCounterMode.BOTH
                else None
            )

    @override_settings(USAGE_COUNTER_REALTIME_MODES="mobile-recordings:both,mobile-billable-recordings:realtime")
    def test_mobile_replay_counters_select_modes_independently_with_one_record_key(self) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        self.legacy[UsageCounter.MOBILE_RECORDINGS].return_value = [(1, 5)]
        self.records.return_value = [
            UsageRecordTotal(team_id=1, organization_id="org-a", usage_key="mobile_replay_recordings", quantity=7)
        ]
        with patch("posthoganalytics.get_feature_flag", return_value="legacy"):
            service = UsageCounterService()
            plan = service.resolve_plan(
                period,
                caller="daily_report",
                counters=(UsageCounter.MOBILE_RECORDINGS, UsageCounter.MOBILE_BILLABLE_RECORDINGS),
            )
        report = service.fetch_report(period, plan=plan)

        assert report.counts == {
            UsageCounter.MOBILE_RECORDINGS: [(1, 5)],
            UsageCounter.MOBILE_BILLABLE_RECORDINGS: [(1, 7)],
        }
        assert report.realtime_counters == {"mobile_recording_count_in_period": {"org-a": 7}}
        assert report.usage_sources == {
            "mobile_recording_count_in_period": UsageCounterMode.BOTH,
            "mobile_billable_recording_count_in_period": UsageCounterMode.REALTIME,
        }
        self.records.assert_called_once_with(period, ("mobile_replay_recordings",), "daily_report")
        self.legacy[UsageCounter.MOBILE_BILLABLE_RECORDINGS].assert_not_called()

    @parameterized.expand([("daily_report", True), ("usage_reports_v2", True), ("quota_limiting", False)])
    def test_legacy_event_reader_preserves_caller_deduplication(
        self, caller: UsageCounterCaller, count_distinct: bool
    ) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        self.legacy[UsageCounter.EVENTS].return_value = [(1, 7)]
        with patch("posthoganalytics.get_feature_flag", return_value="legacy"):
            service = UsageCounterService()
            plan = service.resolve_plan(period, caller=caller, counters=(UsageCounter.EVENTS,))
        assert service.fetch_report(period, plan=plan).counts == {UsageCounter.EVENTS: [(1, 7)]}
        self.events.assert_called_once_with(period.start, period.end, count_distinct=count_distinct)
        self.exceptions.assert_not_called()

    def test_realtime_exception_quota_reader_does_not_query_library_breakdowns(self) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        self.records.return_value = [
            UsageRecordTotal(team_id=1, organization_id="org-a", usage_key="exceptions", quantity=7)
        ]
        with patch("posthoganalytics.get_feature_flag", return_value="realtime"):
            service = UsageCounterService()
            plan = service.resolve_plan(period, caller="quota_limiting", counters=(UsageCounter.EXCEPTIONS,))
        assert service.fetch_report(period, plan=plan).counts == {UsageCounter.EXCEPTIONS: [(1, 7)]}
        self.exceptions.assert_not_called()

    @parameterized.expand([(mode,) for mode in UsageCounterMode])
    def test_legacy_only_counters_preserve_values_and_log_retention_tiers(self, flag_mode: UsageCounterMode) -> None:
        period = DayRange(start=datetime(2026, 5, 4, tzinfo=UTC), end=datetime(2026, 5, 5, tzinfo=UTC))
        counters = (
            UsageCounter.ROWS_SYNCED,
            UsageCounter.FREE_HISTORICAL_ROWS_SYNCED,
            UsageCounter.ROWS_EXPORTED,
            UsageCounter.LOGS_BYTES,
            UsageCounter.LOGS_RETENTION_30D_BYTES,
            UsageCounter.AI_CREDITS,
            UsageCounter.SIGNALS_CREDITS,
            UsageCounter.POSTHOG_CODE_CREDITS,
            UsageCounter.REPLAY_VISION_CREDITS,
        )
        expected = {counter.value: [(1, index + 1)] for index, counter in enumerate(counters)}
        for counter in counters:
            self.legacy[counter].return_value = expected[counter]
        self.logs_retention.side_effect = None
        self.logs_retention.return_value = {
            "14d": [(1, 17)],
            "30d": expected[UsageCounter.LOGS_RETENTION_30D_BYTES],
            "90d": [(2, 23)],
        }
        expected.update(
            {
                "teams_with_logs_retention_14d_bytes_in_period": [(1, 17)],
                "teams_with_logs_retention_90d_bytes_in_period": [(2, 23)],
            }
        )
        with patch("posthoganalytics.get_feature_flag", return_value=flag_mode) as flag:
            service = UsageCounterService()
            plan = service.resolve_plan(period, caller="daily_report", counters=counters)
        report = service.fetch_report(period, plan=plan)

        assert plan.modes == dict.fromkeys(counters, UsageCounterMode.LEGACY)
        assert report.counts == expected
        assert report.usage_sources is None
        assert report.realtime_counters is None
        assert {call.args[0] for call in flag.call_args_list} == {
            f"usage-counter-realtime-{suffix}" for suffix in COUNTER_FLAG_NAMES.values()
        }
        self.records.assert_not_called()
        self.logs_retention.assert_called_once_with(period.start, period.end)
