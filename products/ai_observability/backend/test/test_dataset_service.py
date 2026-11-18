import json
import uuid

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.ai_observability.backend.dataset_service import MAX_DATASETS_PER_TEAM, max_datasets_for_team

TEAM_ID = 42
GET_PAYLOAD = "products.ai_observability.backend.dataset_service.posthoganalytics.get_feature_flag_payload"


class TestMaxDatasetsForTeam(SimpleTestCase):
    def setUp(self) -> None:
        self.team = Team(id=TEAM_ID, organization_id=uuid.uuid4())
        self.user = User(distinct_id="user-distinct-id")

    @parameterized.expand(
        [
            ("override", {"team_configs": {str(TEAM_ID): {"max_datasets": 50}}}, 50),
            ("override_as_json_string", json.dumps({"team_configs": {str(TEAM_ID): {"max_datasets": 50}}}), 50),
            ("override_below_default", {"team_configs": {str(TEAM_ID): {"max_datasets": 5}}}, 5),
            ("no_payload", None, MAX_DATASETS_PER_TEAM),
            ("malformed_json", "{not json", MAX_DATASETS_PER_TEAM),
            ("payload_not_an_object", ["unexpected"], MAX_DATASETS_PER_TEAM),
            ("other_team_only", {"team_configs": {"999999": {"max_datasets": 50}}}, MAX_DATASETS_PER_TEAM),
            ("team_configs_not_an_object", {"team_configs": [50]}, MAX_DATASETS_PER_TEAM),
            ("team_config_not_an_object", {"team_configs": {str(TEAM_ID): 50}}, MAX_DATASETS_PER_TEAM),
            ("zero", {"team_configs": {str(TEAM_ID): {"max_datasets": 0}}}, MAX_DATASETS_PER_TEAM),
            ("boolean", {"team_configs": {str(TEAM_ID): {"max_datasets": True}}}, MAX_DATASETS_PER_TEAM),
            ("string", {"team_configs": {str(TEAM_ID): {"max_datasets": "50"}}}, MAX_DATASETS_PER_TEAM),
            ("float", {"team_configs": {str(TEAM_ID): {"max_datasets": 50.5}}}, MAX_DATASETS_PER_TEAM),
        ]
    )
    def test_resolves_the_limit_from_the_payload(self, _name: str, payload: object, expected: int) -> None:
        with patch(GET_PAYLOAD, return_value=payload):
            self.assertEqual(max_datasets_for_team(team=self.team, user=self.user), expected)

    def test_read_error_resolves_to_the_default(self) -> None:
        error = RuntimeError("flag read failed")
        with (
            patch(GET_PAYLOAD, side_effect=error),
            patch("products.ai_observability.backend.dataset_service.capture_exception") as capture,
        ):
            self.assertEqual(max_datasets_for_team(team=self.team, user=self.user), MAX_DATASETS_PER_TEAM)
        capture.assert_called_once_with(error)

    def test_no_user_resolves_to_the_default_without_a_flag_read(self) -> None:
        with patch(GET_PAYLOAD) as get_payload:
            self.assertEqual(max_datasets_for_team(team=self.team, user=None), MAX_DATASETS_PER_TEAM)
        get_payload.assert_not_called()
