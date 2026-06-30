from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature

from products.approvals.backend.actions.surveys import LaunchSurveyAction
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.surveys.backend.models import Survey


class TestLaunchSurveyActionDetect(APIBaseTest):
    def _create_survey(self, **kwargs) -> Survey:
        defaults = {"team": self.team, "name": "Test survey", "type": "popover", "created_by": self.user}
        defaults.update(kwargs)
        return Survey.objects.create(**defaults)

    def _serializer_view(self, request: MagicMock) -> MagicMock:
        view = MagicMock()
        view.context = {"request": request, "get_team": lambda: self.team}
        return view

    def _viewset_view(self, survey: Survey) -> MagicMock:
        view = MagicMock()
        # A real DRF viewset has no `context` instance attribute, so `_get_instance`
        # falls through to `get_object()`. Delete it so `hasattr` is False as in production.
        del view.context
        view.get_object.return_value = survey
        view.team = self.team
        return view

    def _request(self, data: dict) -> MagicMock:
        request = MagicMock()
        request.method = "PATCH"
        request.data = data
        return request

    def test_detect_true_when_patch_sets_start_date_on_draft(self):
        survey = self._create_survey()
        request = self._request({"start_date": timezone.now().isoformat()})
        assert LaunchSurveyAction.detect(request, self._serializer_view(request), survey) is True

    def test_detect_false_for_plain_edit_of_draft(self):
        survey = self._create_survey()
        request = self._request({"name": "Renamed"})
        assert LaunchSurveyAction.detect(request, self._serializer_view(request), survey) is False

    def test_detect_false_when_already_launched(self):
        survey = self._create_survey(start_date=timezone.now())
        request = self._request({"start_date": timezone.now().isoformat()})
        assert LaunchSurveyAction.detect(request, self._serializer_view(request), survey) is False

    def test_detect_false_for_archived_survey(self):
        survey = self._create_survey(archived=True)
        request = self._request({"start_date": timezone.now().isoformat()})
        assert LaunchSurveyAction.detect(request, self._serializer_view(request), survey) is False

    def test_detect_true_on_dedicated_launch_action_for_draft(self):
        # The dedicated launch action carries no body; reaching it is the launch intent.
        survey = self._create_survey()
        request = MagicMock(method="POST", data={})
        assert LaunchSurveyAction.detect(request, self._viewset_view(survey), request) is True

    def test_detect_false_on_dedicated_launch_action_when_already_launched(self):
        survey = self._create_survey(start_date=timezone.now())
        request = MagicMock(method="POST", data={})
        assert LaunchSurveyAction.detect(request, self._viewset_view(survey), request) is False


class TestSurveyLaunchApprovalGate(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = 8  # admin
        self.organization_membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

    def _create_survey(self, **kwargs) -> Survey:
        defaults = {"team": self.team, "name": "Launch me", "type": "popover", "created_by": self.user}
        defaults.update(kwargs)
        return Survey.objects.create(**defaults)

    def _create_policy(self, **kwargs) -> ApprovalPolicy:
        defaults = {
            "organization": self.organization,
            "team": self.team,
            "action_key": "survey.launch",
            "approver_config": {"quorum": 1, "users": [self.user.id]},
            "allow_self_approve": True,
            "expires_after": timedelta(days=14),
            "enabled": True,
        }
        defaults.update(kwargs)
        return ApprovalPolicy.objects.create(**defaults)

    def _patch_launch(self, survey: Survey):
        return self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"start_date": timezone.now().isoformat()},
            format="json",
        )

    def test_patch_launch_passes_through_without_policy(self):
        survey = self._create_survey()
        response = self._patch_launch(survey)
        assert response.status_code == status.HTTP_200_OK
        survey.refresh_from_db()
        assert survey.start_date is not None
        assert not ChangeRequest.objects.filter(action_key="survey.launch").exists()

    def test_patch_launch_passes_through_when_feature_disabled(self):
        self.organization.available_product_features = []
        self.organization.save()
        self._create_policy()
        survey = self._create_survey()
        response = self._patch_launch(survey)
        assert response.status_code == status.HTTP_200_OK
        survey.refresh_from_db()
        assert survey.start_date is not None

    def test_patch_launch_is_gated_and_then_applied_on_approval(self):
        self._create_policy()
        survey = self._create_survey()

        response = self._patch_launch(survey)
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "approval_required"
        survey.refresh_from_db()
        assert survey.start_date is None  # held, not launched

        cr = ChangeRequest.objects.get(action_key="survey.launch", resource_id=str(survey.id))
        assert cr.state == ChangeRequestState.PENDING

        approve = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/approve/")
        assert approve.status_code == status.HTTP_200_OK

        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.APPLIED
        survey.refresh_from_db()
        assert survey.start_date is not None  # launched

    def test_dedicated_launch_action_is_also_gated(self):
        # Closing the bypass: the dedicated endpoint must not skip approval.
        self._create_policy()
        survey = self._create_survey()

        response = self.client.post(f"/api/projects/{self.team.id}/surveys/{survey.id}/launch/")
        assert response.status_code == status.HTTP_409_CONFLICT
        survey.refresh_from_db()
        assert survey.start_date is None

        cr = ChangeRequest.objects.get(action_key="survey.launch")
        assert cr.resource_id == str(survey.id)  # detail-route pk captured despite POST

    def test_reject_leaves_survey_as_draft(self):
        self._create_policy()
        survey = self._create_survey()
        self._patch_launch(survey)
        cr = ChangeRequest.objects.get(action_key="survey.launch")

        reject = self.client.post(
            f"/api/environments/{self.team.id}/change_requests/{cr.id}/reject/",
            data={"reason": "not yet"},
            format="json",
        )
        assert reject.status_code == status.HTTP_200_OK
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.REJECTED
        survey.refresh_from_db()
        assert survey.start_date is None

    def test_duplicate_launch_request_is_rejected(self):
        self._create_policy()
        survey = self._create_survey()
        first = self._patch_launch(survey)
        assert first.status_code == status.HTTP_409_CONFLICT

        second = self._patch_launch(survey)
        assert second.status_code == status.HTTP_409_CONFLICT
        assert second.json()["code"] == "change_request_pending"
        assert ChangeRequest.objects.filter(action_key="survey.launch", resource_id=str(survey.id)).count() == 1

    def test_plain_edit_of_draft_is_not_gated(self):
        self._create_policy()
        survey = self._create_survey()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/surveys/{survey.id}/",
            data={"description": "just editing"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert not ChangeRequest.objects.filter(action_key="survey.launch").exists()

    def test_stale_survey_fails_to_apply(self):
        self._create_policy()
        survey = self._create_survey()
        self._patch_launch(survey)
        cr = ChangeRequest.objects.get(action_key="survey.launch")

        # Survey is modified after the request is raised, invalidating the precondition.
        survey.name = "Edited after request"
        survey.save()

        approve = self.client.post(f"/api/environments/{self.team.id}/change_requests/{cr.id}/approve/")
        # Quorum is reached but application fails the precondition check.
        cr.refresh_from_db()
        assert cr.state == ChangeRequestState.FAILED
        survey.refresh_from_db()
        assert survey.start_date is None
        assert approve.status_code in (status.HTTP_200_OK, status.HTTP_409_CONFLICT)


class TestLaunchSurveyActionApply(APIBaseTest):
    def _create_survey(self, **kwargs) -> Survey:
        defaults = {"team": self.team, "name": "Apply me", "type": "popover", "created_by": self.user}
        defaults.update(kwargs)
        return Survey.objects.create(**defaults)

    def _intent(self, survey: Survey, start_date=None) -> dict:
        start = (start_date or timezone.now()).isoformat()
        return {
            "survey_id": str(survey.id),
            "survey_name": survey.name,
            "current_state": {"start_date": None},
            "gated_changes": {"start_date": start},
            "full_request_data": {"start_date": start},
            "preconditions": {"updated_at": survey.updated_at.isoformat()},
        }

    def test_apply_launches_survey(self):
        survey = self._create_survey()
        result = LaunchSurveyAction.apply(self._intent(survey), user=self.user)
        survey.refresh_from_db()
        assert survey.start_date is not None
        assert result.id == survey.id

    def test_apply_is_idempotent_when_already_launched(self):
        survey = self._create_survey(start_date=timezone.now())
        existing_start = survey.start_date
        LaunchSurveyAction.apply(self._intent(survey), user=self.user)
        survey.refresh_from_db()
        assert survey.start_date == existing_start

    @parameterized.expand([("targeting_flag",), ("internal_targeting_flag",), ("internal_response_sampling_flag",)])
    def test_apply_activates_managed_flag(self, flag_attr: str):
        from products.feature_flags.backend.models.feature_flag import FeatureFlag

        flag = FeatureFlag.objects.create(team=self.team, key=f"survey-{flag_attr}", created_by=self.user, active=False)
        survey = self._create_survey(**{flag_attr: flag})
        LaunchSurveyAction.apply(self._intent(survey), user=self.user)
        flag.refresh_from_db()
        assert flag.active is True
