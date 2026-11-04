import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, call, patch

from parameterized import parameterized

from posthog.clickhouse.client.connection import Workload
from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.tasks import exporter

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.facade import api, contracts
from products.ai_observability.backend.logic.traces import trace_queries
from products.ai_observability.backend.logic.traces.summary import (
    FailedSummary,
    PendingSummary,
    ReadySummary,
    SummaryEntry,
    SummaryItem,
    SummaryKey,
    workflow_id,
)
from products.ai_observability.backend.logic.traces.summary_store import (
    delete_summary,
    read_summary,
    summary_key,
    write_summary,
)
from products.ai_observability.backend.logic.traces.trace_export import TraceExportRequest
from products.ai_observability.backend.logic.traces.trace_queries import FeedbackEventRow, LoadedTrace, TraceEventRow
from products.ai_observability.backend.models.evaluations import Evaluation
from products.engineering_analytics.backend.facade import api as engineering_analytics_api
from products.engineering_analytics.backend.facade.contracts import BranchPRMatch, GitHubSourceNotConnectedError
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.exports.backend.facade.api import ExportedAsset, InvalidExportContext, read_export_asset_content
from products.surveys.backend.facade.api import (
    LinkedSurveyAnswer,
    LinkedSurveyResponse,
    LinkedSurveyResponses,
    RatingScale,
    SurveyRef,
    UnansweredSurvey,
)

from .logic.traces.rows import (
    CLUSTERING_JOB_ID,
    make_cluster,
    make_cluster_run_event,
    make_evaluation_result_event,
    make_feedback_row,
    make_row,
)
from .logic.traces.test_trace_queries import TraceEventsMixin
from .property_access import hide_event_property

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
TEAM = object()
ACCESS = object()
T1 = T0 + timedelta(seconds=30)
STAMPED = (make_row(uuid="gen-uuid", git_branch="feat/rag", git_repo="acme/app", timestamp=T1),)
ANSWER_BILLING = BranchPRMatch(repo="acme/app", number=42, title="Answer billing questions", state="open")
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


NO_SURVEYS = LinkedSurveyResponses(responses=(), unanswered=())


def _survey_answer(
    question: str, question_type: str, value: str | tuple[str, ...], scale: int | None = None
) -> LinkedSurveyAnswer:
    rating = (
        RatingScale(scale=scale, display="number", lower_bound_label="Bad", upper_bound_label="Great")
        if scale
        else None
    )
    return LinkedSurveyAnswer(
        question_id=question,
        question_index=0,
        question_text=question,
        question_type=question_type,
        rating=rating,
        value=value,
    )


def test_feedback_maps_scores_texts_and_survey_responses_oldest_first() -> None:
    rows = (
        make_feedback_row(uuid="gen-uuid", event="$ai_generation", generation_id="gen-a", timestamp=T0),
        make_feedback_row(uuid="metric", metric_name="helpfulness", metric_value_json="0", parent_id="gen-a"),
        make_feedback_row(
            uuid="text",
            event="$ai_feedback",
            feedback_text_json='"Too long, but correct."',
            timestamp=T0 + timedelta(minutes=2),
        ),
    )
    survey = SurveyRef(id="survey-1", name="Answer quality")
    linked = LinkedSurveyResponses(
        responses=(
            LinkedSurveyResponse(
                survey=survey,
                submission_id="sub-1",
                submitted_at=T0 + timedelta(minutes=1),
                complete=False,
                answers=(
                    _survey_answer("Useful?", "rating", "1", scale=2),
                    _survey_answer("How good?", "rating", "4", scale=5),
                    _survey_answer("What could be better?", "multiple_choice", ("Accuracy", "Tone")),
                    _survey_answer("Anything else?", "open", "Shorter, please."),
                ),
                unavailable=None,
            ),
        ),
        unanswered=(
            UnansweredSurvey(survey=SurveyRef(id="survey-2", name="Follow-up"), shown_at=T0 + timedelta(minutes=3)),
        ),
    )
    with (
        patch.object(api, "load_trace_feedback_rows", return_value=rows),
        patch.object(api, "get_survey_responses_linked_to", return_value=linked),
    ):
        feedback = api.get_trace_feedback(
            team=None,  # type: ignore[arg-type]
            user=None,
            trace_id="trace-1",
            timestamp_hint=None,
            include_surveys=True,
        )

    assert [(score.name, score.value, score.node_id) for score in feedback.scores] == [("helpfulness", "0", "gen-uuid")]
    assert [(response.kind, response.id, response.node_id) for response in feedback.responses] == [
        ("survey", "sub-1", "trace-1"),
        ("text", "text", "trace-1"),
    ]
    survey_response = feedback.responses[0]
    assert isinstance(survey_response, contracts.TraceSurveyResponse)
    assert (survey_response.survey.name, survey_response.complete) == ("Answer quality", False)
    assert [answer.model_dump() for answer in survey_response.answers] == [
        {"kind": "thumbs", "question": "Useful?", "up": True},
        {
            "kind": "rating",
            "question": "How good?",
            "value": "4",
            "scale": 5,
            "lower_label": "Bad",
            "upper_label": "Great",
        },
        {"kind": "choice", "question": "What could be better?", "choices": ["Accuracy", "Tone"]},
        {"kind": "text", "question": "Anything else?", "text": "Shorter, please."},
    ]
    assert [(item.survey.id, item.timestamp) for item in feedback.unanswered] == [
        ("survey-2", T0 + timedelta(minutes=3))
    ]
    assert feedback.summary == contracts.TraceFeedbackSummary(total=3, thumbs_up=1, thumbs_down=0)


SURVEY_READ = call(
    None,
    None,
    property_name="$ai_trace_id",
    property_value="trace-1",
    since=datetime(2026, 9, 1, tzinfo=UTC),
    until=datetime(2026, 10, 2, tzinfo=UTC),
)
WITH_FEEDBACK = (make_feedback_row(uuid="metric", metric_value_json="1", timestamp=T0),)


@parameterized.expand(
    [
        ("a trace with feedback", WITH_FEEDBACK, True, None, [SURVEY_READ], "ok"),
        ("a trace without feedback or a hint", (), True, None, [], "ok"),
        ("a token without the survey scopes", WITH_FEEDBACK, False, None, [], "not_permitted"),
        ("a failed survey read", WITH_FEEDBACK, True, RuntimeError("timeout"), [SURVEY_READ], "failed"),
    ]
)
def test_feedback_reads_the_surveys_linked_to_the_trace_from_its_day(
    _name: str,
    rows: tuple[FeedbackEventRow, ...],
    include_surveys: bool,
    survey_error: Exception | None,
    expected_reads: list[object],
    expected_status: str,
) -> None:
    with (
        patch.object(api, "load_trace_feedback_rows", return_value=rows),
        patch.object(
            api, "get_survey_responses_linked_to", return_value=NO_SURVEYS, side_effect=survey_error
        ) as read_surveys,
        patch.object(api, "capture_exception"),
    ):
        feedback = api.get_trace_feedback(
            team=None,  # type: ignore[arg-type]
            user=None,
            trace_id="trace-1",
            timestamp_hint=None,
            include_surveys=include_surveys,
        )

    assert read_surveys.call_args_list == expected_reads
    assert (feedback.survey_responses_status, len(feedback.scores)) == (expected_status, len(rows))


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

    def test_summarizes_the_latest_run_even_when_a_backfill_carries_an_earlier_event_time(self) -> None:
        evaluation_id = self._detector()
        bulk_create_events(
            [
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-000000000001",
                    team=self.team,
                    timestamp=T0 + timedelta(minutes=5),
                    properties={"$ai_evaluation_id": evaluation_id, "$ai_evaluation_result": False},
                ),
                make_evaluation_result_event(
                    uuid="00000000-0000-0000-0000-000000000002",
                    team=self.team,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={
                        "$ai_evaluation_id": evaluation_id,
                        "$ai_evaluation_result": True,
                        "$ai_evaluation_backfill_id": "backfill-1",
                        "$ai_evaluation_start_time": (T0 + timedelta(days=20)).isoformat(),
                    },
                ),
            ]
        )

        results = api.get_trace_evaluation_results(self.team, self.user, "trace-1")

        assert len(results.results) == 2
        assert (results.summary.passed, results.summary.failed, results.summary.unrated) == (0, 1, 0)
        assert [(node.node_id, node.outcome) for node in results.summary.nodes] == [("trace-1", "fail")]


class TestGetTraceClusters(ClickhouseTestMixin, BaseTest):
    def _run(
        self,
        uuid: str,
        clusters: list[dict[str, object]],
        *,
        days_after: int = 1,
        run_id: str = "1_trace_20260902_030000",
        job_id: str = "",
        job_name: str = "",
    ) -> dict[str, object]:
        return make_cluster_run_event(
            uuid=uuid,
            team=self.team,
            timestamp=T0 + timedelta(days=days_after),
            clusters=clusters,
            run_id=run_id,
            job_id=job_id,
            job_name=job_name,
        )

    def test_returns_the_clusters_that_list_the_trace(self) -> None:
        bulk_create_events(
            [
                self._run(
                    "00000000-0000-0000-0000-0000000c3001",
                    [make_cluster(3, ["trace-1"], title="Billing questions")],
                    run_id=f"1_trace_20260902_030000_{CLUSTERING_JOB_ID}",
                    job_id=CLUSTERING_JOB_ID,
                    job_name="Support conversations",
                ),
                self._run(
                    "00000000-0000-0000-0000-0000000c3002",
                    [make_cluster(0, ["trace-2"]), make_cluster(-1, ["trace-1"], title="Outliers")],
                    days_after=2,
                    run_id="1_trace_20260903_030000",
                ),
            ]
        )

        clusters = api.get_trace_clusters(self.team, self.user, "trace-1", T0).clusters

        assert [(c.cluster_id, c.title, c.job_name, c.is_outlier) for c in clusters] == [
            (3, "Billing questions", "Support conversations", False),
            (-1, "Outliers", None, True),
        ]

    def test_a_viewer_without_cluster_access_gets_no_clusters(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="ai_observability_clusters",
            access_level="none",
            organization_member=self.organization_membership,
        )
        bulk_create_events([self._run("00000000-0000-0000-0000-0000000c3004", [make_cluster(3, ["trace-1"])])])

        assert api.get_trace_clusters(self.team, self.user, "trace-1", T0).clusters == []


class TestTraceSummary(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.jobs: list[contracts.TraceSummaryJob] = []
        delete_summary(summary_key(self.team, self.user, "trace-1"))
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

    def test_a_failed_start_while_joining_a_running_job_keeps_its_entry(self) -> None:
        self._request()
        running = self._stored()
        self.start.side_effect = ConnectionError("temporal is down")

        assert self._request().status == "pending"
        assert self._stored() == running

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


class TestGetTracePullRequest:
    def _lookup(
        self, rows: tuple[TraceEventRow, ...], **resolve: object
    ) -> tuple[contracts.TracePullRequestLookup, MagicMock]:
        resolve_branch = MagicMock(**resolve)
        with (
            patch.object(api, "load_trace_git_rows", return_value=rows),
            patch.object(engineering_analytics_api, "resolve_branch", resolve_branch),
        ):
            lookup = api.get_trace_pull_request(
                team=TEAM,  # type: ignore[arg-type]
                user=None,
                user_access_control=ACCESS,  # type: ignore[arg-type]
                trace_id="trace-1",
                timestamp_hint=T0,
            )
        return lookup, resolve_branch

    def test_resolves_the_latest_branch_with_its_repo_time_and_the_viewers_access(self) -> None:
        rows = (make_row(uuid="span-uuid", git_branch="main", timestamp=T0), *STAMPED)
        other = BranchPRMatch(repo="acme/app", number=7, title=None, state="closed")

        lookup, resolve = self._lookup(rows, return_value=[ANSWER_BILLING, other])

        assert resolve.call_args.kwargs == {
            "team": TEAM,
            "branch": "feat/rag",
            "repo": "acme/app",
            "timestamp": T1,
            "user_access_control": ACCESS,
        }
        assert lookup.pull_request == contracts.TracePullRequest(
            repo_owner="acme", repo_name="app", number=42, title="Answer billing questions"
        )

    @parameterized.expand(
        [
            ("the trace has no branch", (), {"return_value": [ANSWER_BILLING]}, False),
            ("the project has no GitHub source", STAMPED, {"side_effect": GitHubSourceNotConnectedError()}, True),
            (
                "the repo stamp is malformed",
                STAMPED,
                {"side_effect": ValueError("repo must be in 'owner/name' format")},
                True,
            ),
            ("no pull request matches", STAMPED, {"return_value": []}, True),
            (
                "the trace never left the default branch",
                (make_row(uuid="span-uuid", git_branch="main", git_repo="acme/app", timestamp=T0),),
                {"return_value": [ANSWER_BILLING]},
                False,
            ),
        ]
    )
    def test_no_pull_request_when(
        self, _name: str, rows: tuple[TraceEventRow, ...], resolve: dict[str, object], resolves: bool
    ) -> None:
        lookup, resolve_branch = self._lookup(rows, **resolve)

        assert (lookup.pull_request, resolve_branch.called) == (None, resolves)


SPAN = "00000000-0000-0000-0000-000000000011"
GENERATION = "00000000-0000-0000-0000-000000000012"
LATER = "00000000-0000-0000-0000-000000000013"
ROOT_EVENT = "00000000-0000-0000-0000-000000000014"
QUESTION = [{"role": "user", "content": "Which plan fits a team of five?"}]
ANSWER = [{"role": "assistant", "content": "The team plan."}]


class TestTraceExportFile(TraceEventsMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        bulk_create_ai_events(
            [
                self._event(ROOT_EVENT, event="$ai_trace", properties={"$ai_input_state": {"question": "Why?"}}),
                self._event(
                    SPAN,
                    timestamp=T0 + timedelta(seconds=1),
                    properties={"$ai_parent_id": "trace-1", "$ai_span_id": "span-1"},
                ),
                self._event(
                    GENERATION,
                    event="$ai_generation",
                    timestamp=T0 + timedelta(seconds=2),
                    properties={
                        "$ai_parent_id": "span-1",
                        "$ai_input": QUESTION,
                        "$ai_output_choices": ANSWER,
                        "$ai_provider": "openai",
                    },
                ),
                self._event(
                    LATER, timestamp=T0 + timedelta(milliseconds=1500), properties={"$ai_parent_id": "trace-1"}
                ),
            ]
        )

    def _export(self, trace_id: str = "trace-1", created_by: User | None = None) -> ExportedAsset:
        asset = ExportedAsset.objects.create(
            team=self.team,
            export_format="application/json",
            export_context=TraceExportRequest(trace_id=trace_id, timestamp_hint=T0).to_context(),
            created_by=created_by or self.user,
        )
        with suppress(InvalidExportContext):
            exporter.export_asset_direct(asset)
        asset.refresh_from_db()
        return asset

    def _file(self, asset: ExportedAsset) -> contracts.TraceExportFile:
        content = read_export_asset_content(team_id=self.team.pk, asset_id=asset.id)
        assert content is not None, asset.exception
        return contracts.TraceExportFile.model_validate_json(content)

    @parameterized.expand([("one batch", 20), ("a batch per node", 1)])
    def test_writes_the_trace_and_every_node_with_its_io(self, _name: str, batch_size: int) -> None:
        with (
            patch.object(api, "TRACE_EXPORT_NODE_BATCH_SIZE", batch_size),
            patch.object(trace_queries, "query_ai_events", wraps=trace_queries.query_ai_events) as reads,
            patch.object(trace_queries, "execute_hogql_query", wraps=trace_queries.execute_hogql_query) as person_reads,
        ):
            asset = self._export()

        file = self._file(asset)
        assert asset.exception is None
        assert person_reads.call_count == 1
        assert {call.kwargs["workload"] for call in [*reads.call_args_list, *person_reads.call_args_list]} == {
            Workload.OFFLINE
        }
        assert file.trace.id == "trace-1"
        assert file.truncated is False
        assert [node.id for node in file.nodes] == ["trace-1", SPAN, GENERATION, LATER]
        root, generation = file.nodes[0].event, file.nodes[2].event
        assert root is not None and root.properties["$ai_input_state"] == {"question": "Why?"}
        assert generation is not None and generation.properties["$ai_input"] == QUESTION

    def test_a_trace_over_the_event_limit_exports_what_was_read_and_says_so(self) -> None:
        with patch.object(trace_queries, "MAX_TRACE_EVENTS", 2):
            asset = self._export()

        file = self._file(asset)
        assert asset.exception is None
        assert file.truncated is True
        assert [node.id for node in file.nodes] == ["trace-1", SPAN]

    def test_leaves_out_properties_the_creator_may_not_read(self) -> None:
        hide_event_property(self.team, self.user, "$ai_input")

        generation = self._file(self._export()).nodes[2].event

        assert generation is not None
        assert "$ai_input" not in generation.properties
        assert generation.properties["$ai_provider"] == "openai"

    def test_fails_when_the_creator_lost_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "trace-exporter@example.com", "testtest")
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
        )

        asset = self._export(created_by=member)

        assert (asset.exception, asset.has_content) == ("You no longer have access to this trace.", False)

    @parameterized.expand(
        [
            ("a missing trace", "trace-2", None, "This trace is no longer available."),
            ("a file over the cap", "trace-1", 10, "This trace is larger than 250 MB, so it can't be exported."),
        ]
    )
    def test_fails_as_a_user_error_and_leaves_no_file(
        self, _name: str, trace_id: str, max_bytes: int | None, message: str
    ) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(api, "MAX_TRACE_EXPORT_BYTES", max_bytes or api.MAX_TRACE_EXPORT_BYTES),
            patch.object(tempfile, "tempdir", temporary_directory),
        ):
            asset = self._export(trace_id)
            leftover_files = list(Path(temporary_directory).iterdir())

        assert (asset.exception, asset.failure_type) == (message, "user")
        assert leftover_files == []


class TestGetTraceExport(BaseTest):
    def _asset(self, *, trace_id: str = "trace-1", created_by: User | None = None, kind: str = "llm_trace") -> int:
        context = {**TraceExportRequest(trace_id=trace_id, timestamp_hint=None).to_context(), "kind": kind}
        return ExportedAsset.objects.create(
            team=self.team, export_format="application/json", export_context=context, created_by=created_by or self.user
        ).id

    def test_reads_my_export_of_this_trace(self) -> None:
        export = api.get_trace_export(self.team, self.user, "trace-1", self._asset())

        assert (export.status, export.exception) == ("pending", None)

    @parameterized.expand(
        [
            ("another user's export", lambda test: test._asset(created_by=test._teammate()), "trace-1"),
            ("an export of another trace", lambda test: test._asset(), "trace-2"),
            ("an export of another kind", lambda test: test._asset(kind="dataset"), "trace-1"),
        ]
    )
    def test_hides(self, _name: str, asset_for: Callable[["TestGetTraceExport"], int], trace_id: str) -> None:
        with pytest.raises(api.TraceExportNotFoundError):
            api.get_trace_export(self.team, self.user, trace_id, asset_for(self))

    def _teammate(self) -> User:
        return User.objects.create_and_join(self.organization, "teammate@example.com", "testtest")
