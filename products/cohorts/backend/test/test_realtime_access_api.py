from posthog.test.base import APIBaseTest
from unittest import mock

from django.test import override_settings

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.instance_setting import override_instance_config
from posthog.models.team.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.cohorts.backend.models.realtime_request import (
    RealtimeCohortRequest,
    RealtimeCohortRequestKind,
    RealtimeCohortRequestState,
)
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="none",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
)
class TestRealtimeCohortsJoinAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(override_instance_config("REALTIME_COHORT_JOIN_OPEN", True))

    def _join(self, team_id: int | None = None) -> tuple[int, dict]:
        response = self.client.post(f"/api/projects/{team_id or self.team.id}/realtime_cohorts/join/")
        return response.status_code, response.json()

    def _requests(self) -> list[tuple[str, str, int | None]]:
        return list(
            RealtimeCohortRequest.objects.for_team(self.team.id).values_list("kind", "state", "requested_by_id")
        )

    @parameterized.expand([("project",), ("child_environment",)])
    @mock.patch("products.cohorts.backend.api.realtime_access.report_user_action")
    def test_a_join_files_one_request_for_the_root_project_and_a_repeat_files_none(
        self, joined_from: str, report_user_action: mock.MagicMock
    ) -> None:
        team_id = (
            Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team).id
            if joined_from == "child_environment"
            else self.team.id
        )

        first = self._join(team_id)
        repeat = self._join(team_id)

        assert first == repeat == (200, {"state": "setting_up"})
        assert self._requests() == [(RealtimeCohortRequestKind.ENABLE, RealtimeCohortRequestState.QUEUED, self.user.id)]
        assert [call.args[1] for call in report_user_action.call_args_list] == ["realtime cohorts join requested"]
        assert self.client.get(f"/api/projects/{team_id}/realtime_cohorts/join/").json() == {"state": "setting_up"}

    @parameterized.expand(
        [
            ("join_closed", "not_open"),
            # The env list serves the project to the users the rollout flag picks, so a row would change nothing.
            ("env_listed", "refused"),
            ("load_test_row", "refused"),
        ]
    )
    def test_a_join_the_project_cannot_take_files_nothing(self, name: str, state: str) -> None:
        if name == "join_closed":
            self.enterContext(override_instance_config("REALTIME_COHORT_JOIN_OPEN", False))
        elif name == "env_listed":
            self.enterContext(override_settings(REALTIME_COHORT_TEAM_ALLOWLIST=str(self.team.id)))
        else:
            RealtimeCohortTeamAccess.objects.create(
                team=self.team, level=RealtimeCohortLevel.PROCESSING, purpose=RealtimeCohortAccessPurpose.LOAD_TEST
            )

        assert self._join() == (200, {"state": state})
        assert self._requests() == []

    def test_an_impersonated_session_cannot_join(self) -> None:
        with mock.patch("posthog.decorators.is_impersonated_session", return_value=True):
            status, _ = self._join()

        assert status == 403
        assert self._requests() == []

    @parameterized.expand([("viewer", 200), ("none", 403)])
    def test_a_member_needs_view_access_to_cohorts_to_join(self, access_level: str, status: int) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="cohort",
            access_level=access_level,
            organization_member=self.organization_membership,
        )

        assert self._join()[0] == status
        assert len(self._requests()) == (1 if status == 200 else 0)
