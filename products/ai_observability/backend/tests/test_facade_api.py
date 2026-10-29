from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.event.util import bulk_create_events

from products.access_control.backend.models.access_control import AccessControl
from products.ai_observability.backend.facade import api
from products.ai_observability.backend.logic.traces.trace_queries import LoadedTrace
from products.ai_observability.backend.models.evaluations import Evaluation
from products.event_definitions.backend.models.property_definition import PropertyDefinition

from .logic.traces.rows import (
    CLUSTERING_JOB_ID,
    make_cluster,
    make_cluster_run_event,
    make_evaluation_result_event,
    make_row,
)

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


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
                    run_id="1_trace_20260902_030000_job",
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
