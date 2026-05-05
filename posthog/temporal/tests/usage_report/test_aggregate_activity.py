"""Tests for the `aggregate_and_chunk_org_reports` Temporal activity.

These run end-to-end against real MinIO (via `minio_workflow_ctx`) and a
real Postgres test DB (`@pytest.mark.django_db`). Only the "expensive"
gather queries (the ClickHouse + ORM functions in
`posthog.tasks.usage_report`) are mocked — by seeding canned per-spec
JSON files into MinIO ourselves, then letting the activity read,
aggregate, and write back as in production.
"""

import gzip
import json
import uuid
from typing import Any

import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async

from posthog.models import Organization, Team
from posthog.storage import object_storage
from posthog.tasks.usage_report import InstanceMetadata
from posthog.temporal.usage_report import storage
from posthog.temporal.usage_report.activities import aggregate_and_chunk_org_reports
from posthog.temporal.usage_report.queries import QUERIES
from posthog.temporal.usage_report.storage import queries_key, write_json
from posthog.temporal.usage_report.types import AggregateInputs, RunQueryToS3Result, WorkflowContext


@sync_to_async
def _make_org(name: str) -> Organization:
    """Use the sync ORM (so pre_save signals run) wrapped for the async
    test body. `acreate` skips Django signals, which means auto-slug and
    auto-project-creation don't fire — both produce IntegrityErrors for
    Org and Team respectively.
    """
    return Organization.objects.create(name=name, slug=f"test-{uuid.uuid4().hex[:12]}")


@sync_to_async
def _make_team(organization: Organization, name: str) -> Team:
    return Team.objects.create(organization=organization, name=name)


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


def _seed_query_results(ctx: WorkflowContext, team_a_id: int, team_b_id: int) -> list[RunQueryToS3Result]:
    """Write a canned JSON file per QuerySpec into MinIO and return the
    matching `RunQueryToS3Result` list the activity expects as input.
    """
    query_results: list[RunQueryToS3Result] = []
    for spec in QUERIES:
        key = queries_key(ctx, spec.name)
        write_json(key, _canned_query_payload(spec.name, team_a_id, team_b_id))
        query_results.append(RunQueryToS3Result(query_name=spec.name, s3_key=key, duration_ms=1))
    return query_results


def _read_jsonl_gz(key: str) -> list[dict]:
    body = object_storage.read_bytes(key, bucket=storage.bucket())
    assert body is not None, f"missing chunk at {key}"
    return [json.loads(line) for line in gzip.decompress(body).decode("utf-8").splitlines()]


def _read_json(key: str) -> Any:
    body = object_storage.read_bytes(key, bucket=storage.bucket())
    assert body is not None, f"missing object at {key}"
    return json.loads(body)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aggregate_writes_chunks_and_manifest(minio_workflow_ctx: WorkflowContext, activity_environment) -> None:
    org_a = await _make_org("Org A")
    org_b = await _make_org("Org B")
    team_a = await _make_team(org_a, "Team A")
    team_b = await _make_team(org_b, "Team B")

    # Scope the run to just the orgs we created — the shared test DB has
    # pre-seeded orgs that would otherwise inflate the manifest counts.
    ctx = minio_workflow_ctx.model_copy(update={"organization_ids": [str(org_a.id), str(org_b.id)]})
    query_results = _seed_query_results(ctx, team_a.id, team_b.id)

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

    # Manifest matches what the activity returned.
    assert result.manifest_key.endswith("/manifest.json")
    manifest = _read_json(result.manifest_key)
    assert manifest["version"] == 2
    assert manifest["run_id"] == minio_workflow_ctx.run_id
    assert manifest["chunk_count"] == 1
    assert manifest["chunk_keys"] == [chunk_key]
    assert manifest["total_orgs"] == 2

    # Decompress the chunk and inspect the per-org rows.
    rows = _read_jsonl_gz(chunk_key)
    assert len(rows) == 2
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
async def test_aggregate_chunks_into_batches_of_ten_thousand(
    minio_workflow_ctx: WorkflowContext, activity_environment
) -> None:
    """Exercise chunking — set CHUNK_SIZE_ORGS low and verify multiple chunks."""
    from posthog.temporal.usage_report import activities as module

    org = await _make_org("Org X")
    team = await _make_team(org, "T0")

    extra_org_a = await _make_org("Extra A")
    extra_org_b = await _make_org("Extra B")
    extra_team_a = await _make_team(extra_org_a, "EA")
    await _make_team(extra_org_b, "EB")

    # Scope the activity to just the three orgs we created — the shared
    # test DB has pre-seeded internal orgs that would otherwise inflate
    # the chunk counts.
    ctx = minio_workflow_ctx.model_copy(
        update={"organization_ids": [str(org.id), str(extra_org_a.id), str(extra_org_b.id)]}
    )
    query_results = _seed_query_results(ctx, team.id, extra_team_a.id)

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
        all_lines.extend(_read_jsonl_gz(key))
    assert len(all_lines) == 3
    assert {row["organization_id"] for row in all_lines} == {str(org.id), str(extra_org_a.id), str(extra_org_b.id)}

    # Manifest enumerates both chunks
    manifest = _read_json(result.manifest_key)
    assert manifest["chunk_count"] == 2
    assert manifest["chunk_keys"] == result.chunk_keys


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_aggregate_filters_by_organization_ids(minio_workflow_ctx: WorkflowContext, activity_environment) -> None:
    org_a = await _make_org("A")
    org_b = await _make_org("B")
    team_a = await _make_team(org_a, "A")
    team_b = await _make_team(org_b, "B")

    ctx = minio_workflow_ctx.model_copy(update={"organization_ids": [str(org_a.id)]})
    query_results = _seed_query_results(ctx, team_a.id, team_b.id)

    with patch(
        "posthog.temporal.usage_report.activities.get_instance_metadata",
        return_value=_instance_metadata(),
    ):
        result = await activity_environment.run(
            aggregate_and_chunk_org_reports,
            AggregateInputs(ctx=ctx, query_results=query_results),
        )

    assert result.total_orgs == 1
    rows = _read_jsonl_gz(result.chunk_keys[0])
    assert {row["organization_id"] for row in rows} == {str(org_a.id)}
