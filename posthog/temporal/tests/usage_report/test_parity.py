"""End-to-end parity between the legacy Celery `send_all_org_usage_reports`
task and the new Temporal `aggregate-and-chunk-org-reports` activity.

The same seeded `all_data` is fed into both flows against an in-memory S3
and SQS. The Celery path's per-org SQS payloads are decoded
(base64 → gzip → JSON), the Temporal path's per-org JSONL chunks are
decoded (gzip → JSONL), and the per-org dicts must match byte-for-byte
for every org both paths emit.

This is intentionally end-to-end rather than walking private helpers — we
want drift in chunk framing, multi-key fan-out, SQS encoding, or activity
wiring to fail the test, not just drift in one shared serializer.
"""

import io
import gzip
import json
import base64
import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from django.db import connection
from django.test.utils import CaptureQueriesContext

from posthog.models import Organization, Team
from posthog.tasks.usage_report import send_all_org_usage_reports
from posthog.temporal.usage_report.activities import aggregate_and_chunk_org_reports
from posthog.temporal.usage_report.queries import QUERIES
from posthog.temporal.usage_report.storage import queries_key, write_json
from posthog.temporal.usage_report.types import AggregateInputs, AggregateResult, RunQueryToS3Result, WorkflowContext
from posthog.utils import get_previous_day


def _all_destination_keys() -> list[str]:
    """Every key `_get_team_report` reads, derived from the registry so we
    don't have to keep the test in sync with the spec list by hand.
    """
    keys: list[str] = []
    for spec in QUERIES:
        if spec.output == "multi":
            keys.extend(spec.multi_keys_mapping.values())
        else:
            keys.append(spec.name)
    return keys


def _seed_all_data(team_a_id: int, team_b_id: int, team_c_id: int) -> dict[str, dict[int, int]]:
    """A non-trivial `all_data` covering several destination keys.

    Realistic enough to prove the team→org rollup math is identical across
    both paths: different team distributions per metric, some teams missing
    from some metrics, and at least one org with multiple teams summed. All
    other destination keys (derived from the registry) get an empty dict
    so `_get_team_report`'s lookups don't KeyError.
    """
    interesting: dict[str, dict[int, int]] = {
        "teams_with_event_count_in_period": {team_a_id: 100, team_b_id: 50, team_c_id: 25},
        "teams_with_enhanced_persons_event_count_in_period": {team_a_id: 80, team_b_id: 40},
        "teams_with_recording_count_in_period": {team_a_id: 8, team_c_id: 3},
        "teams_with_recording_bytes_in_period": {team_a_id: 1_234_567, team_c_id: 89_012},
        "teams_with_decide_requests_count_in_period": {team_a_id: 1_000, team_b_id: 200, team_c_id: 50},
        "teams_with_local_evaluation_requests_count_in_period": {team_b_id: 5},
        "teams_with_dashboard_count": {team_a_id: 4, team_b_id: 2, team_c_id: 1},
        "teams_with_ff_count": {team_a_id: 7, team_b_id: 3},
        "teams_with_survey_count": {team_a_id: 1, team_c_id: 2},
        "teams_with_web_events_count_in_period": {team_a_id: 60, team_b_id: 30},
        "teams_with_exceptions_captured_in_period": {team_a_id: 5, team_b_id: 1},
        "teams_with_web_exceptions_captured_in_period": {team_a_id: 5},
        "teams_with_node_exceptions_captured_in_period": {team_b_id: 1},
        "teams_with_api_queries_count": {team_a_id: 10},
        "teams_with_api_queries_read_bytes": {team_a_id: 1_500_000},
    }
    return {key: interesting.get(key, {}) for key in _all_destination_keys()}


def _install_in_memory_object_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """Patch the S3 helpers used by the Temporal flow to read/write a dict.

    Returns the dict so the test can read what was written and pre-seed
    keys for `load_all_data` to read back.
    """
    s3: dict[str, bytes] = {}

    def _write(key: str, content: Any, extras: Any = None, bucket: Any = None) -> None:
        s3[key] = content.encode("utf-8") if isinstance(content, str) else content

    def _write_stream(key: str, fileobj: io.IOBase, extras: Any = None, bucket: Any = None) -> None:
        s3[key] = fileobj.read()

    def _read_bytes(key: str, bucket: Any = None, *, missing_ok: bool = False) -> bytes | None:
        if key not in s3:
            if missing_ok:
                return None
            raise FileNotFoundError(key)
        return s3[key]

    monkeypatch.setattr("posthog.storage.object_storage.write", _write)
    monkeypatch.setattr("posthog.storage.object_storage.write_stream", _write_stream)
    monkeypatch.setattr("posthog.storage.object_storage.read_bytes", _read_bytes)
    return s3


def _install_fake_sqs_producer(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Patch `ee.sqs.SQSProducer.get_sqs_producer` to return a fake producer.

    Returns the list each `send_message` call appends to, so the test can
    decode the captured per-org payloads after the Celery task runs.
    """
    captured: list[dict[str, Any]] = []

    class _FakeProducer:
        def send_message(self, message_body: str, message_attributes: dict[str, str]) -> dict[str, str]:
            captured.append({"body": message_body, "attributes": message_attributes})
            return {"MessageId": "fake"}

    monkeypatch.setattr("ee.sqs.SQSProducer.get_sqs_producer", lambda _name: _FakeProducer())
    return captured


def _seed_temporal_query_files(
    s3: dict[str, bytes],
    ctx: WorkflowContext,
    seeded: dict[str, dict[int, int]],
) -> list[RunQueryToS3Result]:
    """Pre-write the per-query S3 files the activity reads via `load_all_data`.

    Inverts `multi_keys_mapping` so multi-output specs end up in the
    source-key shape the aggregator expects to fan back out.
    """
    results: list[RunQueryToS3Result] = []
    for spec in QUERIES:
        key = queries_key(ctx, spec.name)
        if spec.output == "multi":
            payload: Any = {
                source: [{"team_id": tid, "total": cnt} for tid, cnt in seeded[dest].items()]
                for source, dest in spec.multi_keys_mapping.items()
            }
        else:
            payload = [{"team_id": tid, "total": cnt} for tid, cnt in seeded[spec.name].items()]
        write_json(key, payload)
        assert key in s3, f"_install_in_memory_object_storage didn't capture write for {key}"
        results.append(RunQueryToS3Result(query_name=spec.name, s3_key=key, duration_ms=0))
    return results


def _decode_celery_sqs_messages(messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Reverse `_queue_report`: base64 → gzip → JSON, keyed by org_id."""
    out: dict[str, dict[str, Any]] = {}
    for msg in messages:
        decoded = json.loads(gzip.decompress(base64.b64decode(msg["body"])).decode("utf-8"))
        out[decoded["organization_id"]] = decoded["usage_report"]
    return out


def _decode_temporal_chunks(s3: dict[str, bytes], chunk_keys: list[str]) -> dict[str, dict[str, Any]]:
    """Reverse the activity's chunk writer: gzip → JSONL → per-org dict."""
    out: dict[str, dict[str, Any]] = {}
    for key in chunk_keys:
        gz = gzip.decompress(s3[key]).decode("utf-8")
        for line in gz.splitlines():
            obj = json.loads(line)
            out[obj["organization_id"]] = obj["usage_report"]
    return out


@pytest.mark.django_db(transaction=True)
def test_end_to_end_parity_celery_task_vs_temporal_activity(
    activity_environment: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both production paths must produce the same per-org bytes for the
    same `all_data` snapshot. Drift here is what billing's parity check
    will catch in production.

    Two orgs × three teams (org_a has two teams so the multi-team rollup
    is exercised; org_b has one). The shared test DB may already contain
    other orgs with no usage; those are excluded by the Celery path's
    `has_non_zero_usage` gate, so we compare only the orgs Celery actually
    sends.
    """
    org_a = Organization.objects.create(name="E2E Parity A")
    org_b = Organization.objects.create(name="E2E Parity B")
    team_a1 = Team.objects.create(organization=org_a, name="A1")
    team_a2 = Team.objects.create(organization=org_a, name="A2")
    team_b = Team.objects.create(organization=org_b, name="B")

    celery_at = datetime(2026, 5, 5, 0, 0, 0, tzinfo=UTC)
    period_start, period_end = get_previous_day(celery_at)
    seeded = _seed_all_data(team_a1.id, team_a2.id, team_b.id)

    s3 = _install_in_memory_object_storage(monkeypatch)
    sqs_messages = _install_fake_sqs_producer(monkeypatch)

    # Don't let the Celery task short-circuit on the kill-switch flag,
    # and silence the start/end PostHog `capture` calls.
    monkeypatch.setattr("posthoganalytics.feature_enabled", lambda *a, **kw: False)
    monkeypatch.setattr("posthog.tasks.usage_report.get_ph_client", lambda *a, **kw: mock.MagicMock())
    # Skip the heavy gather queries — both paths use this same `seeded`
    # dict, just shaped differently for each entry point.
    monkeypatch.setattr(
        "posthog.tasks.usage_report._get_all_usage_data_as_team_rows",
        lambda *a, **kw: seeded,
    )

    # ---- Celery path ----
    send_all_org_usage_reports(at=celery_at.isoformat(), skip_capture_event=True)
    celery_per_org = _decode_celery_sqs_messages(sqs_messages)

    # ---- Temporal path ----
    ctx = WorkflowContext(
        run_id="e2e-parity-test",
        period_start=period_start,
        period_end=period_end,
        date_str=period_start.strftime("%Y-%m-%d"),
        organization_ids=None,
    )
    query_results = _seed_temporal_query_files(s3, ctx, seeded)
    # The activity is async; the test is sync so DB setup can use the
    # ORM directly. `asyncio.run` drives the activity in a fresh loop.
    result: AggregateResult = asyncio.run(
        activity_environment.run(
            aggregate_and_chunk_org_reports,
            AggregateInputs(ctx=ctx, query_results=query_results),
        )
    )
    temporal_per_org = _decode_temporal_chunks(s3, result.chunk_keys)

    # Both of our test orgs should have non-zero usage, so Celery should
    # have queued them. Sanity-check that before comparing, otherwise a
    # silent zero-usage filter could hide actual drift.
    assert str(org_a.id) in celery_per_org
    assert str(org_b.id) in celery_per_org

    # Both paths skip zero-usage orgs; comparing on the Celery key set
    # keeps the assertion focused on the orgs billing actually receives.
    for org_id, celery_dict in celery_per_org.items():
        assert org_id in temporal_per_org, f"Celery emitted {org_id} but Temporal didn't"
        celery_json = json.dumps(celery_dict, sort_keys=True, default=str)
        temporal_json = json.dumps(temporal_per_org[org_id], sort_keys=True, default=str)
        assert celery_json == temporal_json, (
            f"Drift between Celery SQS payload and Temporal chunk for org {org_id}.\n"
            f"Celery (first 500 chars):\n{celery_json[:500]}\n"
            f"Temporal (first 500 chars):\n{temporal_json[:500]}"
        )

    # Sanity-check the rollup math — org_a sums its two teams, org_b
    # only has one. If this drifts, the rest of the parity numbers are
    # suspect.
    assert temporal_per_org[str(org_a.id)]["event_count_in_period"] == 100 + 50
    assert temporal_per_org[str(org_b.id)]["event_count_in_period"] == 25
    assert temporal_per_org[str(org_a.id)]["team_count"] == 2
    assert temporal_per_org[str(org_b.id)]["team_count"] == 1


@pytest.mark.django_db
def test_temporal_build_org_reports_does_not_run_per_org_membership_queries() -> None:
    """The Temporal-local `aggregator.build_org_reports` must fetch
    organization membership counts in bulk. The legacy Celery facade still
    runs one `OrganizationMembership.count()` per organization inside its
    team loop — that's the cost we lifted out of the
    `aggregate-and-chunk-org-reports` activity by routing it through the
    aggregator's own builder instead of the shared one.
    """
    from posthog.temporal.usage_report.aggregator import (
        build_org_reports as temporal_build_org_reports,
        get_org_user_counts,
    )

    # Create a meaningful number of fresh orgs/teams so the per-org N+1
    # would have clear daylight from the bulk-fetch path. Without this,
    # query counts are low enough that any reasonable cap would pass.
    fresh_orgs: list[Organization] = []
    for i in range(20):
        org = Organization.objects.create(name=f"Bulk Org {i}")
        Team.objects.create(organization=org, name=f"Team {i}")
        fresh_orgs.append(org)

    period_start = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
    all_data: dict[str, dict[int, int]] = {key: {} for key in _all_destination_keys()}

    with CaptureQueriesContext(connection) as captured:
        org_user_counts = get_org_user_counts()
        temporal_build_org_reports(all_data, period_start, org_user_counts)

    # The Temporal path runs ~2 queries (teams + bulk memberships)
    # regardless of org count. The legacy Celery path runs 1 + N. Cap
    # well below `1 + N` so any per-org N+1 here blows the test, while
    # leaving slack for harmless query-count drift (savepoints etc.).
    assert len(captured.captured_queries) <= 5, (
        f"Temporal build_org_reports issued {len(captured.captured_queries)} "
        f"queries — with {len(fresh_orgs)} fresh orgs this looks like a "
        f"per-org N+1, which dominates wall-clock for the aggregation activity."
    )
