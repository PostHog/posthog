"""Pure-logic tests for the aggregator module.

These cover the building blocks the aggregation activity composes:
`load_all_data`, `iter_chunk_lines`, `batched`, `build_manifest`,
`filter_org_reports`, `sort_org_reports`. No Django / Temporal / S3
required.
"""

import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import patch

from posthog.tasks.usage_report import InstanceMetadata, OrgReport
from posthog.temporal.usage_report.aggregator import (
    batched,
    build_manifest,
    filter_org_reports,
    iter_chunk_lines,
    load_all_data,
    sort_org_reports,
)
from posthog.temporal.usage_report.types import Manifest, RunQueryToS3Result, WorkflowContext


def _ctx(run_id: str = "abc") -> WorkflowContext:
    return WorkflowContext(
        run_id=run_id,
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str="2026-05-04",
    )


# ---- batched -------------------------------------------------------------


def test_batched_yields_full_and_remainder() -> None:
    assert list(batched([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_batched_empty_input() -> None:
    assert list(batched([], 3)) == []


def test_batched_exact_multiple() -> None:
    assert list(batched([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]


def test_batched_invalid_size_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        list(batched([1, 2], 0))


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


# ---- iter_chunk_lines ----------------------------------------------------


class _FakeOrgReport:
    """Minimal stand-in: only `organization_id` is touched directly by
    `iter_chunk_lines`. The rest goes through `serialize_full_org_report`,
    which we mock per test.
    """

    def __init__(self, organization_id: str) -> None:
        self.organization_id = organization_id


def test_iter_chunk_lines_emits_id_and_report_with_usage_flag() -> None:
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
        ({"organization_id": "org-a", "usage_report": {"event_count_in_period": 10, "has_non_zero_usage": True}}, True),
        (
            {"organization_id": "org-b", "usage_report": {"event_count_in_period": 0, "has_non_zero_usage": False}},
            False,
        ),
    ]


def test_iter_chunk_lines_treats_missing_flag_as_falsy() -> None:
    org = _FakeOrgReport("org-x")
    with patch(
        "posthog.temporal.usage_report.aggregator.serialize_full_org_report",
        return_value={"event_count_in_period": 0},  # no has_non_zero_usage
    ):
        out = list(iter_chunk_lines(cast(list[OrgReport], [org]), instance_metadata=cast(InstanceMetadata, None)))
    assert out[0][1] is False


# ---- build_manifest ------------------------------------------------------


def test_build_manifest_returns_typed_manifest() -> None:
    ctx = _ctx(run_id="run-1")
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
    assert manifest.region == "US"
    assert manifest.site_url == "https://us.posthog.com"
    assert manifest.bucket == "posthog-billing-usage-reports"
    assert manifest.chunk_keys == ["chunks/chunk_0000.jsonl.gz", "chunks/chunk_0001.jsonl.gz"]
    assert manifest.chunk_count == 2
    assert manifest.total_orgs == 12345
    assert manifest.total_orgs_with_usage == 678


# ---- filter_org_reports / sort_org_reports -------------------------------


def test_filter_org_reports_no_filter_returns_all() -> None:
    reports = cast(dict[str, OrgReport], {"a": _FakeOrgReport("a"), "b": _FakeOrgReport("b")})
    assert filter_org_reports(reports, None) is reports
    assert filter_org_reports(reports, []) is reports  # empty list also no-ops


def test_filter_org_reports_with_ids_keeps_only_requested() -> None:
    reports = cast(
        dict[str, OrgReport],
        {"a": _FakeOrgReport("a"), "b": _FakeOrgReport("b"), "c": _FakeOrgReport("c")},
    )
    out = filter_org_reports(reports, ["a", "c", "missing"])
    assert set(out.keys()) == {"a", "c"}


def test_sort_org_reports_orders_by_organization_id() -> None:
    reports = cast(
        dict[str, OrgReport],
        {
            "z": _FakeOrgReport("z"),
            "a": _FakeOrgReport("a"),
            "m": _FakeOrgReport("m"),
        },
    )
    out = sort_org_reports(reports)
    assert [r.organization_id for r in out] == ["a", "m", "z"]
