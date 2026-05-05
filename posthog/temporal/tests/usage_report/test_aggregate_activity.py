"""Tests for the `aggregate_and_chunk_org_reports` Temporal activity.

Mocks S3 with an in-memory dict and patches the underlying gather queries to
return canned per-team rows, so we can verify the activity correctly:

* reconstructs the legacy `all_data` dict from S3 query files,
* fans out `output="multi"` results into the right destination keys,
* runs `_get_team_report` + `_add_team_report_to_org_reports` per team,
* writes gzipped JSONL chunks to S3,
* writes a manifest JSON enumerating the chunks.
"""

import gzip
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team
from posthog.tasks.usage_report import InstanceMetadata
from posthog.temporal.usage_report.activities import aggregate_and_chunk_org_reports
from posthog.temporal.usage_report.queries import QUERIES
from posthog.temporal.usage_report.types import AggregateInputs, RunQueryToS3Result, WorkflowContext


def _canned_query_payload(query_name: str, team_a_id: int, team_b_id: int) -> Any:
    """Default payload per query — uses team rows where it makes sense, and
    multi-key dicts for the three multi-output specs.
    """
    if query_name == "all_event_metrics":
        return {
            "helicone_events": [],
            "langfuse_events": [],
            "keywords_ai_events": [],
            "traceloop_events": [],
            "web_events": [(team_a_id, 7), (team_b_id, 11)],
            "web_lite_events": [],
            "node_events": [],
            "android_events": [],
            "flutter_events": [],
            "ios_events": [],
            "go_events": [],
            "java_events": [],
            "react_native_events": [],
            "ruby_events": [],
            "python_events": [(team_a_id, 3)],
            "php_events": [],
            "dotnet_events": [],
            "elixir_events": [],
            "unity_events": [],
            "rust_events": [],
        }
    if query_name == "exceptions_captured":
        return {
            "total": [[team_a_id, 5]],
            "web": [[team_a_id, 5]],
            "web_lite": [],
            "node": [],
            "android": [],
            "flutter": [],
            "ios": [],
            "go": [],
            "java": [],
            "react_native": [],
            "ruby": [],
            "python": [],
            "unknown": [],
        }
    if query_name == "api_queries_metrics":
        return {"count": [(team_b_id, 100)], "read_bytes": [(team_b_id, 5_000_000)]}

    if query_name == "teams_with_event_count_in_period":
        return [(team_a_id, 100), (team_b_id, 50)]
    if query_name == "teams_with_recording_count_in_period":
        return [(team_a_id, 8)]

    # Postgres ORM-style queries return dicts with team_id/total
    if query_name in (
        "teams_with_dashboard_count",
        "teams_with_ff_count",
        "teams_with_survey_count",
        "teams_with_group_types_total",
    ):
        return [{"team_id": team_a_id, "total": 2}, {"team_id": team_b_id, "total": 1}]

    # Everything else gets an empty result list — keeps the test focused on
    # the few interesting metrics above.
    return []


def _instance_metadata() -> InstanceMetadata:
    return InstanceMetadata(
        deployment_infrastructure="test",
        realm="cloud",
        period={
            "start_inclusive": "2026-05-04T00:00:00+00:00",
            "end_inclusive": "2026-05-04T23:59:59.999999+00:00",
        },
        site_url="https://us.posthog.com",
        product="cloud",
        helm=None,
        clickhouse_version=None,
        users_who_logged_in=None,
        users_who_logged_in_count=None,
        users_who_signed_up=None,
        users_who_signed_up_count=None,
        table_sizes=None,
        plugins_installed=None,
        plugins_enabled=None,
        instance_tag="test-tag",
    )


class _S3:
    """Minimal in-memory stand-in for posthog.storage.object_storage."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def write(self, key: str, content: Any, extras: dict | None = None) -> None:
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.objects[key] = content

    def write_stream(self, key: str, fileobj: Any, extras: dict | None = None) -> None:
        self.objects[key] = fileobj.read()

    def read_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def s3() -> Iterable[_S3]:
    fake = _S3()
    with patch("posthog.temporal.usage_report.storage.object_storage", fake):
        yield fake


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aggregate_writes_chunks_and_manifest(s3: _S3, activity_environment) -> None:
    org_a = await Organization.objects.acreate(name="Org A")
    org_b = await Organization.objects.acreate(name="Org B")
    team_a = await Team.objects.acreate(organization=org_a, name="Team A")
    team_b = await Team.objects.acreate(organization=org_b, name="Team B")

    ctx = WorkflowContext(
        run_id="run-test",
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str="2026-05-04",
    )

    # Seed S3 with one canned JSON per QuerySpec, and build the matching
    # `query_results` list the activity expects as input.
    query_results = []
    for spec in QUERIES:
        key = f"tasks/billing/usage_reports/2026-05-04/run-test/queries/{spec.name}.json"
        s3.objects[key] = json.dumps(
            _canned_query_payload(spec.name, team_a.id, team_b.id),
            default=str,
        ).encode("utf-8")
        query_results.append(RunQueryToS3Result(query_name=spec.name, s3_key=key, duration_ms=1))

    with patch(
        "posthog.temporal.usage_report.activities.get_instance_metadata",
        return_value=_instance_metadata(),
    ):
        result = await activity_environment.run(
            aggregate_and_chunk_org_reports,
            AggregateInputs(ctx=ctx, query_results=query_results),
        )

    assert result.total_orgs == 2

    # Exactly one chunk written, since 2 orgs fits well under the 10k batch.
    assert len(result.chunk_keys) == 1
    chunk_key = result.chunk_keys[0]
    assert chunk_key.endswith("/chunks/chunk_0000.jsonl.gz")

    # Manifest exists and matches.
    assert result.manifest_key.endswith("/run-test/manifest.json")
    manifest = json.loads(s3.objects[result.manifest_key])
    assert manifest["version"] == 2
    assert manifest["run_id"] == "run-test"
    assert manifest["chunk_count"] == 1
    assert manifest["chunk_keys"] == [chunk_key]
    assert manifest["total_orgs"] == 2

    # Decompress the chunk and inspect the per-org rows.
    chunk_lines = gzip.decompress(s3.objects[chunk_key]).decode("utf-8").splitlines()
    assert len(chunk_lines) == 2
    rows = [json.loads(line) for line in chunk_lines]
    by_org = {row["organization_id"]: row["usage_report"] for row in rows}
    assert set(by_org.keys()) == {str(org_a.id), str(org_b.id)}

    # multi-key fan-out: web events from `all_event_metrics` landed in the
    # destination key on each org's report.
    assert by_org[str(org_a.id)]["web_events_count_in_period"] == 7
    assert by_org[str(org_b.id)]["web_events_count_in_period"] == 11

    # exceptions_captured "total" maps to the flat counter on the org's report.
    assert by_org[str(org_a.id)]["exceptions_captured_in_period"] == 5
    assert by_org[str(org_b.id)]["exceptions_captured_in_period"] == 0

    # api_queries_metrics fans out to count + read_bytes destination keys.
    assert by_org[str(org_b.id)]["api_queries_query_count"] == 100
    assert by_org[str(org_b.id)]["api_queries_bytes_read"] == 5_000_000

    # has_non_zero_usage is computed and present on every line.
    assert by_org[str(org_a.id)]["has_non_zero_usage"] is True
    assert by_org[str(org_b.id)]["has_non_zero_usage"] is True

    # team breakdown is present and matches.
    assert by_org[str(org_a.id)]["teams"][str(team_a.id)]["event_count_in_period"] == 100


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aggregate_chunks_into_batches_of_ten_thousand(s3: _S3, activity_environment) -> None:
    """Exercise chunking — set CHUNK_SIZE_ORGS low and verify multiple chunks."""
    from posthog.temporal.usage_report import activities as module

    org = await Organization.objects.acreate(name="Org X")
    teams = []
    for i in range(5):
        teams.append(await Team.objects.acreate(organization=org, name=f"T{i}"))

    ctx = WorkflowContext(
        run_id="run-chunked",
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str="2026-05-04",
    )

    # Produce three orgs by mocking `_get_teams_for_usage_reports` to return
    # teams across three orgs, then force `CHUNK_SIZE_ORGS=2` to split them.
    extra_org_a = await Organization.objects.acreate(name="Extra A")
    extra_org_b = await Organization.objects.acreate(name="Extra B")
    extra_team_a = await Team.objects.acreate(organization=extra_org_a, name="EA")
    await Team.objects.acreate(organization=extra_org_b, name="EB")

    query_results = []
    for spec in QUERIES:
        key = f"tasks/billing/usage_reports/2026-05-04/run-chunked/queries/{spec.name}.json"
        s3.objects[key] = (
            json.dumps(_canned_query_payload(spec.name, teams[0].id, extra_team_a.id), default=str)
        ).encode("utf-8")
        query_results.append(RunQueryToS3Result(query_name=spec.name, s3_key=key, duration_ms=1))

    with (
        patch.object(module, "CHUNK_SIZE_ORGS", 2),
        patch(
            "posthog.temporal.usage_report.activities.get_instance_metadata",
            return_value=_instance_metadata(),
        ),
    ):
        result = await activity_environment.run(
            aggregate_and_chunk_org_reports,
            AggregateInputs(ctx=ctx, query_results=query_results),
        )

    # 3 orgs / 2 per chunk = 2 chunks (2 + 1)
    assert result.total_orgs == 3
    assert len(result.chunk_keys) == 2

    all_lines: list[dict] = []
    for key in result.chunk_keys:
        body = gzip.decompress(s3.objects[key]).decode("utf-8")
        all_lines.extend(json.loads(line) for line in body.splitlines())
    assert len(all_lines) == 3
    assert {row["organization_id"] for row in all_lines} == {str(org.id), str(extra_org_a.id), str(extra_org_b.id)}
    # Manifest enumerates both chunks
    manifest = json.loads(s3.objects[result.manifest_key])
    assert manifest["chunk_count"] == 2
    assert manifest["chunk_keys"] == result.chunk_keys


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aggregate_filters_by_organization_ids(s3: _S3, activity_environment) -> None:
    org_a = await Organization.objects.acreate(name="A")
    org_b = await Organization.objects.acreate(name="B")
    team_a = await Team.objects.acreate(organization=org_a, name="A")
    team_b = await Team.objects.acreate(organization=org_b, name="B")

    ctx = WorkflowContext(
        run_id="run-filter",
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str="2026-05-04",
        organization_ids=[str(org_a.id)],
    )

    query_results = []
    for spec in QUERIES:
        key = f"tasks/billing/usage_reports/2026-05-04/run-filter/queries/{spec.name}.json"
        s3.objects[key] = json.dumps(_canned_query_payload(spec.name, team_a.id, team_b.id), default=str).encode(
            "utf-8"
        )
        query_results.append(RunQueryToS3Result(query_name=spec.name, s3_key=key, duration_ms=1))

    with patch(
        "posthog.temporal.usage_report.activities.get_instance_metadata",
        return_value=_instance_metadata(),
    ):
        result = await activity_environment.run(
            aggregate_and_chunk_org_reports,
            AggregateInputs(ctx=ctx, query_results=query_results),
        )

    assert result.total_orgs == 1
    chunk_lines = gzip.decompress(s3.objects[result.chunk_keys[0]]).decode("utf-8").splitlines()
    rows = [json.loads(line) for line in chunk_lines]
    assert {row["organization_id"] for row in rows} == {str(org_a.id)}
