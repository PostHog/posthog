from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.models import Team
from posthog.models.event.util import bulk_create_events

from ...logic.traces.rows import make_evaluation_result_event
from .trace_fixtures import GENERATION, T0, encode_segment, restrict_property

EVALUATION_RESULT = "00000000-0000-0000-0000-000000000003"


def _create_evaluation_result(team: Team) -> None:
    bulk_create_events(
        [
            make_evaluation_result_event(
                uuid=EVALUATION_RESULT,
                team=team,
                timestamp=T0 + timedelta(seconds=30),
                properties={
                    "$ai_target_event_id": GENERATION,
                    "$ai_evaluation_name": "Answers the question",
                    "$ai_evaluation_reasoning": "Direct answer.",
                },
            )
        ]
    )


class TestTraceEvaluationsView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/evaluations/"

    def test_returns_the_results_in_camel_case(self) -> None:
        _create_evaluation_result(self.team)

        response = self.client.get(self._url(encode_segment("trace-1")))

        assert response.status_code == 200
        body = response.json()
        assert body["results"][0] | {"timestamp": None} == {
            "id": EVALUATION_RESULT,
            "evaluationId": None,
            "evaluationName": "Answers the question",
            "targetNodeId": GENERATION,
            "outcome": "pass",
            "label": "True",
            "score": None,
            "reasoning": "Direct answer.",
            "timestamp": None,
            "isBackfill": False,
        }
        assert body["summary"] == {
            "passed": 1,
            "failed": 0,
            "unrated": 0,
            "nodes": [{"nodeId": GENERATION, "outcome": "pass"}],
        }

    def test_an_unknown_trace_has_no_results(self) -> None:
        response = self.client.get(self._url(encode_segment("trace-2")))

        assert (response.status_code, response.json()) == (
            200,
            {"results": [], "summary": {"passed": 0, "failed": 0, "unrated": 0, "nodes": []}},
        )

    def test_rejects_an_unencoded_trace_id(self) -> None:
        assert self.client.get(self._url("trace-1")).status_code == 400

    def test_masks_properties_the_viewer_may_not_read(self) -> None:
        restrict_property(self, "$ai_evaluation_reasoning")
        _create_evaluation_result(self.team)

        result = self.client.get(self._url(encode_segment("trace-1"))).json()["results"][0]

        assert (result["reasoning"], result["outcome"]) == (None, "pass")
