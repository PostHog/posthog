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

from .logic.traces.rows import make_evaluation_result_event, make_row

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
