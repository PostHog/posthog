"""Pure-logic tests for the aggregator module.

These cover the building blocks the aggregation activity composes:
`load_all_data`, `iter_chunk_lines`, `build_manifest`,
`write_org_report_chunks`.
No Django / Temporal / S3 required.
"""

import gzip
import json
import weakref
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import patch

from posthog.tasks.usage_report import (
    InstanceMetadata,
    OrgReport,
    UsageReportCounters,
    iter_reports_with_usage_counter_metadata,
)
from posthog.temporal.tests.usage_report.test_aggregate_activity import _instance_metadata
from posthog.temporal.usage_report.aggregator import (
    add_pre_logs_distinct_patterns_patch_defaults,
    add_pre_mcp_event_count_patch_defaults,
    add_pre_replay_vision_spend_projection_patch_defaults,
    add_pre_sandbox_compute_patch_defaults,
    add_pre_transactional_emails_patch_defaults,
    build_manifest,
    iter_chunk_lines,
    load_all_data,
    load_usage_counter_report,
    write_org_report_chunks,
)
from posthog.temporal.usage_report.types import (
    AggregateInputs,
    Manifest,
    ReportCompleteness,
    RunQueryToS3Result,
    WorkflowContext,
)
from posthog.usage_counters import (
    UsageCounterComparison,
    UsageCounterComparisonRows,
    UsageCounterMode,
    UsageCounterReport,
    UsageCounterService,
)
from posthog.utils import DayRange


def _ctx(run_id: str = "abc", report_completeness: ReportCompleteness = "partial") -> WorkflowContext:
    return WorkflowContext(
        run_id=run_id,
        workflow_started_at=datetime(2026, 5, 5, 1, 45, 0, tzinfo=UTC),
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str="2026-05-04",
        report_completeness=report_completeness,
    )


# ---- load_all_data -------------------------------------------------------


def _seed_s3(s3: dict[str, bytes], spec_name: str, payload) -> str:
    key = f"queries/{spec_name}.json"
    s3[key] = json.dumps(payload, default=str).encode("utf-8")
    return key


def _patch_query_index(specs: dict) -> Any:
    return patch.dict(
        "posthog.temporal.usage_report.queries.QUERY_INDEX",
        specs,
        clear=True,
    )


class _SingleSpec:
    """Minimal QuerySpec stand-in for unit tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.output = "single"
        self.multi_keys_mapping: dict[str, str] = {}


class _MultiSpec:
    def __init__(self, name: str, mapping: dict[str, str]) -> None:
        self.name = name
        self.output = "multi"
        self.multi_keys_mapping = mapping


def test_load_all_data_single_output_uses_spec_name_as_key() -> None:
    s3: dict[str, bytes] = {}
    key = _seed_s3(s3, "teams_with_event_count_in_period", [(1, 100), (2, 50)])
    results = [RunQueryToS3Result(query_name="teams_with_event_count_in_period", s3_key=key, duration_ms=1)]

    with (
        _patch_query_index({"teams_with_event_count_in_period": _SingleSpec("teams_with_event_count_in_period")}),
        patch("posthog.temporal.usage_report.aggregator.read_json", side_effect=lambda k: json.loads(s3[k])),
    ):
        all_data = load_all_data(results)

    assert all_data == {"teams_with_event_count_in_period": {1: 100, 2: 50}}


def test_load_all_data_multi_output_fans_out_destination_keys() -> None:
    s3: dict[str, bytes] = {}
    payload = {"web_events": [(1, 7), (2, 11)], "node_events": [(2, 3)]}
    key = _seed_s3(s3, "all_event_metrics", payload)
    results = [RunQueryToS3Result(query_name="all_event_metrics", s3_key=key, duration_ms=1)]

    spec = _MultiSpec(
        "all_event_metrics",
        mapping={
            "web_events": "teams_with_web_events_count_in_period",
            "node_events": "teams_with_node_events_count_in_period",
        },
    )
    with (
        _patch_query_index({"all_event_metrics": spec}),
        patch("posthog.temporal.usage_report.aggregator.read_json", side_effect=lambda k: json.loads(s3[k])),
    ):
        all_data = load_all_data(results)

    assert all_data == {
        "teams_with_web_events_count_in_period": {1: 7, 2: 11},
        "teams_with_node_events_count_in_period": {2: 3},
    }


def test_load_all_data_multi_output_missing_source_key_yields_empty() -> None:
    """If the upstream query didn't emit one of the expected source_keys,
    the destination still gets an empty mapping (not a KeyError)."""
    s3: dict[str, bytes] = {}
    key = _seed_s3(s3, "all_event_metrics", {"web_events": [(1, 1)]})
    results = [RunQueryToS3Result(query_name="all_event_metrics", s3_key=key, duration_ms=1)]

    spec = _MultiSpec(
        "all_event_metrics",
        mapping={
            "web_events": "teams_with_web_events_count_in_period",
            "ruby_events": "teams_with_ruby_events_count_in_period",
        },
    )
    with (
        _patch_query_index({"all_event_metrics": spec}),
        patch("posthog.temporal.usage_report.aggregator.read_json", side_effect=lambda k: json.loads(s3[k])),
    ):
        all_data = load_all_data(results)

    assert all_data["teams_with_web_events_count_in_period"] == {1: 1}
    assert all_data["teams_with_ruby_events_count_in_period"] == {}


def test_load_all_data_defaults_compute_for_pre_patch_workflow_history() -> None:
    all_data: dict[str, dict[int, int]] = {}
    add_pre_sandbox_compute_patch_defaults(all_data, [])

    assert all_data["teams_with_sandbox_compute_credits_used_in_period"] == {}
    assert all_data["teams_with_sandbox_compute_cpu_millicore_seconds_in_period"] == {}
    assert all_data["teams_with_sandbox_compute_memory_mib_seconds_in_period"] == {}


@pytest.mark.parametrize(
    "add_defaults,query_name",
    [
        (add_pre_logs_distinct_patterns_patch_defaults, "teams_with_logs_distinct_patterns_in_period"),
        (add_pre_transactional_emails_patch_defaults, "teams_with_workflow_transactional_emails_sent_in_period"),
        (add_pre_mcp_event_count_patch_defaults, "teams_with_mcp_event_count_in_period"),
    ],
)
def test_load_all_data_defaults_single_query_for_pre_patch_workflow_history(
    add_defaults: Callable[[dict[str, dict[int, int]], list[RunQueryToS3Result]], None], query_name: str
) -> None:
    all_data: dict[str, dict[int, int]] = {}
    add_defaults(all_data, [])

    assert all_data == {query_name: {}}

    patched_data: dict[str, dict[int, int]] = {query_name: {1: 2}}
    add_defaults(patched_data, [RunQueryToS3Result(query_name=query_name, s3_key="unused", duration_ms=1)])

    assert patched_data == {query_name: {1: 2}}


def test_load_all_data_defaults_replay_vision_spend_projection_for_pre_patch_workflow_history() -> None:
    all_data: dict[str, dict[int, int]] = {}
    add_pre_replay_vision_spend_projection_patch_defaults(all_data, [])

    assert all_data == {
        "teams_with_replay_vision_scanner_projected_credits": {},
        "teams_with_replay_vision_backfill_committed_credits": {},
    }

    patched_data: dict[str, dict[int, int]] = {}
    results = [RunQueryToS3Result(query_name="replay_vision_spend_projection", s3_key="unused", duration_ms=1)]
    add_pre_replay_vision_spend_projection_patch_defaults(patched_data, results)

    assert patched_data == {}


def test_load_all_data_does_not_default_compute_for_patched_workflow_history() -> None:
    all_data: dict[str, dict[int, int]] = {}
    results = [RunQueryToS3Result(query_name="sandbox_compute_usage", s3_key="unused", duration_ms=1)]
    add_pre_sandbox_compute_patch_defaults(all_data, results)

    assert all_data == {}


@pytest.mark.parametrize(
    "state", ["zero", "failed_scan", "missing_result", "missing_object", "invalid_json", "legacy", "partial"]
)
def test_shadow_coverage_distinguishes_zero_from_failure(state: str) -> None:
    ctx = _ctx(report_completeness="partial" if state == "partial" else "complete")
    if state != "legacy":
        with patch("posthoganalytics.get_feature_flag", return_value="both"):
            ctx.usage_counter_plan = UsageCounterService().resolve_plan(
                DayRange(start=ctx.period_start, end=ctx.period_end),
                complete=ctx.report_completeness == "complete",
            )
    result = RunQueryToS3Result(query_name="usage_counters", s3_key="shadow.json", duration_ms=1)
    payload = json.dumps(
        {
            "counts": {"teams_with_cdp_billable_invocations_in_period": [[1, 12]]},
            "usage_sources": {"cdp_billable_invocations_in_period": "both"},
            "counter_comparisons": None
            if state == "failed_scan"
            else {"cdp_billable_invocations_in_period": {"legacy_by_team": {1: 12}, "realtime_by_team": {}}},
        }
    ).encode()
    with patch(
        "posthog.storage.object_storage.read_bytes", return_value=b"invalid" if state == "invalid_json" else payload
    ) as read:
        if state == "missing_object":
            read.side_effect = FileNotFoundError("missing")
        inputs = AggregateInputs(
            ctx=ctx, query_results=[], counter_result=None if state in {"missing_result", "legacy"} else result
        )
        if state in {"missing_result", "missing_object", "invalid_json"}:
            with pytest.raises((ValueError, FileNotFoundError)):
                load_usage_counter_report(inputs)
            return
        counter_report = load_usage_counter_report(inputs)
        if state != "legacy":
            assert counter_report.counts == {"teams_with_cdp_billable_invocations_in_period": [(1, 12)]}
    org = _empty_org_report("org-a", cdp_billable_invocations_in_period=12)
    org.teams["1"] = _empty_org_report("org-a", cdp_billable_invocations_in_period=12)
    assert list(
        iter_reports_with_usage_counter_metadata([org], counter_report, caller="usage_reports_v2", date=ctx.date_str)
    ) == [org]
    assert org.cdp_billable_invocations_in_period == 12
    if state == "legacy":
        assert org.usage_sources is None
        read.assert_not_called()
    else:
        assert org.usage_sources is not None
        assert org.usage_sources["cdp_billable_invocations_in_period"] == "both"
    assert org.counter_comparisons == (
        {"cdp_billable_invocations_in_period": {"legacy": 12, "realtime": 0}} if state in {"zero", "partial"} else None
    )


def test_counter_comparisons_follow_current_team_ownership() -> None:
    previous_owner = _empty_org_report("org-a")
    previous_owner.teams["1"] = _empty_org_report("org-a")
    current_owner = _empty_org_report("org-b", cdp_billable_invocations_in_period=100)
    current_owner.teams["2"] = _empty_org_report("org-b", cdp_billable_invocations_in_period=100)
    counter_report = UsageCounterReport(
        counts={},
        usage_sources={"cdp_billable_invocations_in_period": UsageCounterMode.BOTH},
        counter_comparisons={
            "cdp_billable_invocations_in_period": UsageCounterComparisonRows(
                legacy_by_team={2: 100}, realtime_by_team={2: {"org-a": 60, "org-b": 40}}
            )
        },
    )

    with patch("posthog.tasks.usage_report.ph_scoped_capture") as capture:
        assert list(
            iter_reports_with_usage_counter_metadata(
                iter((previous_owner, current_owner)), counter_report, caller="usage_reports_v2", date="2026-05-04"
            )
        ) == [previous_owner, current_owner]

    assert previous_owner.counter_comparisons == {"cdp_billable_invocations_in_period": {"legacy": 0, "realtime": 0}}
    assert current_owner.counter_comparisons == {"cdp_billable_invocations_in_period": {"legacy": 100, "realtime": 100}}
    capture.assert_not_called()


def test_counter_metadata_does_not_retain_streamed_reports() -> None:
    references: list[weakref.ReferenceType[OrgReport]] = []

    def reports() -> Iterator[OrgReport]:
        for team_id in range(4):
            report = _empty_org_report(str(team_id), event_count_in_period=1)
            report.teams[str(team_id)] = _empty_org_report(str(team_id), event_count_in_period=1)
            references.append(weakref.ref(report))
            yield report

    counter_report = UsageCounterReport(
        counts={},
        usage_sources={"event_count_in_period": UsageCounterMode.BOTH},
        counter_comparisons={
            "event_count_in_period": UsageCounterComparisonRows(
                legacy_by_team=dict.fromkeys(range(4), 1),
                realtime_by_team={team_id: {str(team_id): 2} for team_id in range(4)},
            )
        },
    )
    output = iter_reports_with_usage_counter_metadata(
        reports(), counter_report, caller="usage_reports_v2", date="2026-05-04"
    )
    for team_id in range(4):
        report = next(output)
        assert report.organization_id == str(team_id)
        assert report.counter_comparisons == {"event_count_in_period": {"legacy": 1, "realtime": 2}}
        assert sum(ref() is not None for ref in references) == 1
        del report
    assert next(output, None) is None


def test_missing_organization_diagnostics_split_without_losing_comparisons() -> None:
    rows = {team: {f"00000000-0000-0000-0000-{team:012d}": 7} for team in range(10_000)}
    report = UsageCounterReport(
        counts={},
        usage_sources={"event_count_in_period": UsageCounterMode.BOTH},
        counter_comparisons={
            "event_count_in_period": UsageCounterComparisonRows(legacy_by_team={}, realtime_by_team=rows)
        },
    )
    with patch("posthog.tasks.usage_report.ph_scoped_capture") as scoped:
        assert (
            list(iter_reports_with_usage_counter_metadata([], report, caller="usage_reports_v2", date="2026-05-04"))
            == []
        )
    calls = scoped.return_value.__enter__.return_value.call_args_list
    assert len(calls) > 1
    recovered: dict[str, dict[str, UsageCounterComparison]] = {}
    for call in calls:
        assert len(json.dumps(call.kwargs).encode("utf-8")) < 900 * 1024
        batch = call.kwargs["properties"]["organizations"]
        assert not recovered.keys() & batch.keys()
        recovered.update(batch)
    assert recovered == {
        org: {"event_count_in_period": {"legacy": 0, "realtime": quantity}}
        for orgs in rows.values()
        for org, quantity in orgs.items()
    }


# ---- iter_chunk_lines ----------------------------------------------------


class _FakeOrgReport:
    """Minimal stand-in: only `organization_id` is touched directly by
    `iter_chunk_lines`. The rest goes through `serialize_full_org_report`,
    which we mock per test.
    """

    def __init__(self, organization_id: str) -> None:
        self.organization_id = organization_id


def test_iter_chunk_lines_emits_id_and_report() -> None:
    org_a = _FakeOrgReport("org-a")
    org_b = _FakeOrgReport("org-b")

    def fake_serialize(report, _meta) -> dict:
        if report.organization_id == "org-a":
            return {"event_count_in_period": 10, "has_non_zero_usage": True}
        return {"event_count_in_period": 0, "has_non_zero_usage": False}

    with patch("posthog.temporal.usage_report.aggregator.serialize_full_org_report", side_effect=fake_serialize):
        result = list(
            iter_chunk_lines(cast(list[OrgReport], [org_a, org_b]), instance_metadata=cast(InstanceMetadata, None))
        )

    assert result == [
        {"organization_id": "org-a", "usage_report": {"event_count_in_period": 10, "has_non_zero_usage": True}},
        {"organization_id": "org-b", "usage_report": {"event_count_in_period": 0, "has_non_zero_usage": False}},
    ]


# ---- build_manifest ------------------------------------------------------


def test_build_manifest_returns_typed_manifest() -> None:
    ctx = _ctx(run_id="run-1", report_completeness="complete")
    with (
        patch("posthog.temporal.usage_report.aggregator.settings") as mock_settings,
        patch("posthog.temporal.usage_report.aggregator.bucket", return_value="posthog-billing-usage-reports"),
    ):
        mock_settings.SITE_URL = "https://us.posthog.com"
        manifest = build_manifest(
            ctx,
            chunk_keys=["chunks/chunk_0000.jsonl.gz", "chunks/chunk_0001.jsonl.gz"],
            total_orgs=12345,
            total_orgs_with_usage=678,
            region="US",
            version=2,
        )

    assert isinstance(manifest, Manifest)
    assert manifest.version == 2
    assert manifest.run_id == "run-1"
    assert manifest.date == "2026-05-04"
    assert manifest.period_start == ctx.period_start
    assert manifest.period_end == ctx.period_end
    assert manifest.report_completeness == "complete"
    assert manifest.region == "US"
    assert manifest.site_url == "https://us.posthog.com"
    assert manifest.bucket == "posthog-billing-usage-reports"
    assert manifest.chunk_keys == ["chunks/chunk_0000.jsonl.gz", "chunks/chunk_0001.jsonl.gz"]
    assert manifest.chunk_count == 2
    assert manifest.total_orgs == 12345
    assert manifest.total_orgs_with_usage == 678


# ---- write_org_report_chunks ---------------------------------------------


def _empty_org_report(organization_id: str, **overrides: Any) -> OrgReport:
    """Construct an `OrgReport` with every counter zeroed out. Override
    individual counters per test to exercise the `has_non_zero_usage`
    branches without listing the full field set every time.
    """
    counter_fields: dict[str, Any] = {f.name: 0 for f in dataclasses.fields(UsageReportCounters)}
    # `dwh_*_storage_in_s3_in_mib` are floats, but `0` works fine.
    counter_fields.update(overrides)
    return OrgReport(
        date="2026-05-04",
        organization_id=organization_id,
        organization_name="org",
        organization_created_at="2024-01-01T00:00:00+00:00",
        organization_user_count=0,
        team_count=0,
        teams={},
        **counter_fields,
    )


@pytest.mark.parametrize("active_orgs", [0, 4, 5])
def test_chunks_stream_reports_and_preserve_counts(active_orgs: int) -> None:
    references: list[weakref.ReferenceType[OrgReport]] = []
    objects: dict[str, bytes] = {}

    def reports() -> Iterator[OrgReport]:
        for index in range(active_orgs + 1):
            report = _empty_org_report(
                str(index),
                event_count_in_period=int(index < active_orgs),
                dashboard_count=10,
                usage_sources={"cdp_billable_invocations_in_period": "both"},
                counter_comparisons={"cdp_billable_invocations_in_period": {"legacy": 0, "realtime": 50}},
            )
            references.append(weakref.ref(report))
            yield report

    def write(key: str, content: str | bytes, **kwargs: Any) -> None:
        objects[key] = content.encode() if isinstance(content, str) else content
        assert sum(ref() is not None for ref in references) <= 1

    with patch("posthog.storage.object_storage.write", side_effect=write):
        result = write_org_report_chunks(
            _ctx(), reports(), _instance_metadata(), chunk_size=2, version=2, region="US", check_cancelled=lambda: None
        )

    assert result.total_orgs == active_orgs + 1
    assert result.total_orgs_with_usage == active_orgs
    assert len(result.chunk_keys) == (active_orgs + 1) // 2
    chunks = [[json.loads(line) for line in gzip.decompress(objects[key]).splitlines()] for key in result.chunk_keys]
    assert [row["organization_id"] for chunk in chunks for row in chunk] == [str(i) for i in range(active_orgs)]
    assert all(0 < len(chunk) <= 2 for chunk in chunks)
    manifest = json.loads(objects[result.manifest_key])
    assert manifest["total_orgs"] == result.total_orgs
    assert manifest["total_orgs_with_usage"] == result.total_orgs_with_usage
    assert manifest["chunk_keys"] == result.chunk_keys


@pytest.mark.parametrize(
    "failure, report_count",
    [
        ("upload", 3),
        # The third report trips the check between reports.
        ("cancel", 3),
        # Both reports fit in the first chunk, so only the check before the manifest can trip.
        ("cancel", 2),
    ],
)
def test_failed_chunk_run_does_not_publish_manifest(failure: str, report_count: int) -> None:
    written: list[str] = []

    def write(key: str, content: str | bytes, **kwargs: Any) -> None:
        if failure == "upload" and written:
            raise OSError("upload failed")
        written.append(key)

    def check_cancelled() -> None:
        if failure == "cancel" and written:
            raise RuntimeError("cancelled")

    with (
        patch("posthog.storage.object_storage.write", side_effect=write),
        pytest.raises((OSError, RuntimeError)),
    ):
        write_org_report_chunks(
            _ctx(),
            (_empty_org_report(str(i), event_count_in_period=1) for i in range(report_count)),
            _instance_metadata(),
            chunk_size=2,
            version=2,
            region="US",
            check_cancelled=check_cancelled,
        )
    assert not any(key.endswith("manifest.json") for key in written)
