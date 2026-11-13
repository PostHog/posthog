from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.event_definitions.backend.models.property_definition import PropertyDefinition

from .trace_fixtures import GENERATION, T0, create_trace, encode_segment

SCORE = "00000000-0000-0000-0000-000000000004"
FEEDBACK = "00000000-0000-0000-0000-000000000005"


def _create_feedback(team: Team) -> None:
    def event(uuid: str, name: str, properties: dict[str, object]) -> dict[str, object]:
        return {
            "event": name,
            "event_uuid": uuid,
            "distinct_id": "user-1",
            "team": team,
            "timestamp": T0 + timedelta(minutes=1),
            "properties": {"$ai_trace_id": "trace-1", **properties},
        }

    create_trace(team)
    bulk_create_ai_events(
        [
            event(
                SCORE,
                "$ai_metric",
                {"$ai_metric_name": "helpfulness", "$ai_metric_value": 0, "$ai_parent_id": GENERATION},
            ),
            event(FEEDBACK, "$ai_feedback", {"$ai_feedback_text": "Too long, but correct."}),
        ]
    )


class TestTraceFeedbackView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/feedback/"

    def test_returns_the_feedback_in_camel_case(self) -> None:
        _create_feedback(self.team)

        response = self.client.get(self._url(encode_segment("trace-1")))

        assert response.status_code == 200
        body = response.json()
        assert [score | {"timestamp": None} for score in body["scores"]] == [
            {"id": SCORE, "name": "helpfulness", "value": "0", "nodeId": GENERATION, "timestamp": None}
        ]
        assert [(item["kind"], item["text"], item["nodeId"]) for item in body["responses"]] == [
            ("text", "Too long, but correct.", "trace-1")
        ]
        assert body["summary"]["total"] == 2
        assert [(step["nodeId"], step["responseCount"], step["total"]) for step in body["steps"]] == [
            (GENERATION, 0, 1),
            ("trace-1", 1, 1),
        ]
        assert body["surveyResponsesStatus"] == "ok"

    @parameterized.expand(
        [
            ("only the trace scope", ["llm_analytics:read"], "not_permitted"),
            ("the survey response scopes too", ["llm_analytics:read", "survey:read", "query:read"], "ok"),
        ]
    )
    def test_includes_survey_responses_only_for_a_token_with_the_survey_scopes(
        self, _name: str, scopes: list[str], expected: str
    ) -> None:
        _create_feedback(self.team)
        headers = {"authorization": f"Bearer {self.create_personal_api_key_with_scopes(scopes)}"}
        self.client.logout()

        response = self.client.get(self._url(encode_segment("trace-1")), headers=headers)

        assert response.status_code == 200
        assert (response.json()["surveyResponsesStatus"], response.json()["summary"]["total"]) == (expected, 2)

    def test_an_unknown_trace_has_no_feedback(self) -> None:
        response = self.client.get(self._url(encode_segment("trace-2")))

        assert response.status_code == 200
        assert (response.json()["scores"], response.json()["responses"], response.json()["summary"]["total"]) == (
            [],
            [],
            0,
        )

    def test_rejects_an_unencoded_trace_id(self) -> None:
        assert self.client.get(self._url("trace-1")).status_code == 400

    def test_masks_feedback_the_viewer_may_not_read(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$ai_feedback_text", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        _create_feedback(self.team)

        body = self.client.get(self._url(encode_segment("trace-1"))).json()

        assert (len(body["scores"]), body["responses"]) == (1, [])
