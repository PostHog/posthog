from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.event.util import bulk_create_events

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces.summary import (
    FailedSummary,
    PendingSummary,
    ReadySummary,
    SummaryEntry,
    SummaryItem,
    SummaryKey,
    workflow_id,
)
from products.ai_observability.backend.logic.traces.summary_store import read_summary, summary_key, write_summary
from products.ai_observability.backend.logic.traces.trace_queries import LoadedTrace
from products.ai_observability.backend.models.evaluations import Evaluation
from products.event_definitions.backend.models.property_definition import PropertyDefinition

from .logic.traces.rows import make_evaluation_result_event, make_row
from .property_access import hide_event_property

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
READY_SUMMARY = ReadySummary(
    title="Refund request",
    bullets=(SummaryItem(text="The user asks for a refund.", node_id="gen-1"),),
    notes=(),
    flow="ask → refuse",
    model="gpt-4.1-mini",
    generated_at=T0,
)


def test_root_node_is_the_trace_and_nodes_keep_event_uuids() -> None:
    rows = (
        make_row(uuid="span-uuid", span_id="span", timestamp=T0),
        make_row(uuid="gen-uuid", event="$ai_generation", parent_id="span", timestamp=T0),
    )
    with patch.object(api, "load_trace", return_value=LoadedTrace(rows=rows, person=None)):
        trace = api.get_trace(team=None, user=None, trace_id="trace-1", timestamp_hint=None)  # type: ignore[arg-type]

    root = trace.tree[0]
    assert (root.id, root.kind, root.name) == ("trace-1", "trace", "Trace")
    assert [(node.id, [child.id for child in node.children]) for node in root.children] == [("span-uuid", ["gen-uuid"])]
    assert [row.id for row in trace.timeline] == ["span-uuid", "gen-uuid"]


def test_missing_trace_raises_not_found() -> None:
    with patch.object(api, "load_trace", return_value=LoadedTrace(rows=(), person=None)):
        with pytest.raises(api.TraceNotFoundError):
            api.get_trace(team=None, user=None, trace_id="missing", timestamp_hint=None)  # type: ignore[arg-type]


class TestGetTraceEvaluationResults(ClickhouseTestMixin, BaseTest):
    def _detector(self, team: Team | None = None, *, deleted: bool = False, stored_config: object = None) -> str:
        evaluation = Evaluation.objects.create(
            team=team or self.team,
            name="Mentions a competitor",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "Does the answer mention a competitor?"},
            output_type="boolean",
            output_config={"true_is_failure": True},
            deleted=deleted,
        )
        if stored_config is not None:
            Evaluation.objects.filter(id=evaluation.id).update(output_config=stored_config)
        return str(evaluation.id)

    def _other_team(self) -> Team:
        return Team.objects.create(organization=self.organization, name="other")

    def _detector_hidden_from_the_viewer(self) -> str:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="evaluation", access_level="none", organization_member=self.organization_membership
        )
        return self._detector()

    @parameterized.expand(
        [
            ("an active detector", lambda test: test._detector(), "fail"),
            ("a deleted detector", lambda test: test._detector(deleted=True), "fail"),
            ("another team's detector", lambda test: test._detector(test._other_team()), "pass"),
            ("a detector the viewer cannot read", lambda test: test._detector_hidden_from_the_viewer(), "pass"),
            ("an id that is not a UUID", lambda test: "not-a-uuid", "pass"),
            (
                "a detector whose stored config is not an object",
                lambda test: test._detector(stored_config=["true_is_failure"]),
                "pass",
            ),
        ]
    )
    def test_applies_the_results_stored_output_config(
        self, _name: str, evaluation_id_for: Callable[["TestGetTraceEvaluationResults"], str], outcome: str
    ) -> None:
        bulk_create_events(
            [
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-000000000001",
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={"$ai_evaluation_id": evaluation_id_for(self)},
                )
            ]
        )

        [result] = api.get_trace_evaluation_results(self.team, self.user, "trace-1").results

        assert result.outcome == outcome

    def test_reads_a_registered_boolean_property_like_its_ingested_value(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team,
            name="$ai_evaluation_applicable",
            property_type="Boolean",
            type=PropertyDefinition.Type.EVENT,
        )
        bulk_create_events(
            [
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-000000000001",
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={"$ai_evaluation_applicable": False},
                )
            ]
        )

        [result] = api.get_trace_evaluation_results(self.team, None, "trace-1").results

        assert (result.outcome, result.label) == ("inconclusive", "N/A")

    def test_lists_results_by_their_event_time_newest_first(self) -> None:
        live = "00000000-0000-0000-0000-000000000001"
        backfill = "00000000-0000-0000-0000-000000000002"
        bulk_create_events(
            [
                make_evaluation_result_event(uuid=live, team=self.team, timestamp=T0 + timedelta(minutes=5)),
                make_evaluation_result_event(
                    uuid=backfill,
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={
                        "$ai_evaluation_start_time": (T0 + timedelta(days=20)).isoformat(),
                        "$ai_evaluation_backfill_id": "backfill-1",
                    },
                ),
            ]
        )

        results = api.get_trace_evaluation_results(self.team, None, "trace-1").results

        assert [(result.id, result.is_backfill) for result in results] == [(live, False), (backfill, True)]


class TestTraceSummary(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.jobs: list[contracts.TraceSummaryJob] = []
        patcher = patch.object(api, "start_trace_summary", side_effect=self.jobs.append)
        self.start = patcher.start()
        self.addCleanup(patcher.stop)

    def _request(self, *, regenerate: bool = False) -> contracts.TraceSummary:
        return api.request_trace_summary(self.team, self.user, "trace-1", T0, regenerate=regenerate)

    def _stored(self) -> SummaryEntry | None:
        return read_summary(summary_key(self.team, self.user, "trace-1"))

    def _store(self, entry: SummaryEntry) -> None:
        write_summary(summary_key(self.team, self.user, "trace-1"), entry)

    def test_a_new_request_writes_pending_and_starts_one_job(self) -> None:
        assert self._request().status == "pending"

        [job] = self.jobs
        assert (job.trace_id, job.timestamp_hint, job.requester_id) == ("trace-1", T0, self.user.pk)
        assert SummaryKey.for_job(job) == summary_key(self.team, self.user, "trace-1")
        stored = self._stored()
        assert isinstance(stored, PendingSummary) and job.requested_at == stored.requested_at

    def test_a_repeat_while_pending_keeps_the_entry_and_attaches(self) -> None:
        self._request()
        stored = self._stored()

        assert self._request(regenerate=True).status == "pending"
        assert self._stored() == stored
        assert len(self.jobs) == 2 and len({workflow_id(job) for job in self.jobs}) == 1

    @parameterized.expand([("kept", False, "ready", 0), ("regenerated", True, "pending", 1)])
    def test_ready_is_returned_unless_regenerate(
        self, _name: str, regenerate: bool, expected_status: str, expected_starts: int
    ) -> None:
        self._store(READY_SUMMARY)

        assert self._request(regenerate=regenerate).status == expected_status
        assert len(self.jobs) == expected_starts

    def test_retry_after_a_failure_starts_again(self) -> None:
        self._store(FailedSummary(reason="provider_error", failed_at=T0))

        assert self._request().status == "pending"
        assert len(self.jobs) == 1

    def test_a_job_that_cannot_start_reads_as_failed(self) -> None:
        self.start.side_effect = ConnectionError("temporal is down")

        summary = self._request()

        assert summary.failure is not None and (summary.status, summary.failure.reason) == ("failed", "error")
        assert api.get_trace_summary(self.team, self.user, "trace-1").status == "failed"

    def test_get_hides_another_fingerprint(self) -> None:
        restricted = User.objects.create_and_join(self.organization, "restricted@example.com", "testtest")
        hide_event_property(self.team, restricted, "$ai_input")
        self._store(READY_SUMMARY)

        with pytest.raises(api.TraceSummaryNotFoundError):
            api.get_trace_summary(self.team, restricted, "trace-1")
        summary = api.get_trace_summary(self.team, self.user, "trace-1")
        assert summary.content is not None and summary.content.bullets[0].node_id == "gen-1"

    def test_consent_withdrawn_hides_a_ready_entry(self) -> None:
        self._store(READY_SUMMARY)
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        self.team.refresh_from_db()

        with pytest.raises(api.AIDataProcessingNotApprovedError):
            api.get_trace_summary(self.team, self.user, "trace-1")
        with pytest.raises(api.AIDataProcessingNotApprovedError):
            self._request(regenerate=True)
        assert self.jobs == []
