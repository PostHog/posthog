from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, Team, User

from products.dashboards.backend.constants import DEFAULT_WIDGET_LIST_LIMIT
from products.dashboards.backend.widget_registry import SURVEY_RESULTS_WIDGET_TYPE, validate_widget_config
from products.dashboards.backend.widgets.survey_results import run_survey_results_widget
from products.surveys.backend.models import Survey


def _block_survey_for_member(team: Team, survey: Survey, member: User) -> None:
    from ee.models.rbac.access_control import AccessControl  # noqa: PLC0415

    team.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": "Access control"}]
    team.organization.save()
    membership = OrganizationMembership.objects.get(organization=team.organization, user=member)
    AccessControl.objects.create(
        team=team,
        resource="survey",
        resource_id=str(survey.id),
        organization_member=membership,
        access_level="none",
    )


class TestSurveyResultsWidgetConfig(APIBaseTest):
    def test_config_defaults_to_unconfigured(self) -> None:
        validated = validate_widget_config(SURVEY_RESULTS_WIDGET_TYPE, {})
        assert validated.get("surveyId") is None
        assert validated["limit"] == DEFAULT_WIDGET_LIST_LIMIT

    def test_blank_survey_id_normalizes_to_none(self) -> None:
        validated = validate_widget_config(SURVEY_RESULTS_WIDGET_TYPE, {"surveyId": ""})
        assert validated.get("surveyId") is None

    @parameterized.expand(
        [
            ("limit_too_high", {"limit": 100}),
            ("unknown_key", {"evil": True}),
            ("bad_date_from", {"dateRange": {"date_from": "-2y"}}),
        ]
    )
    def test_rejects_invalid_config(self, _name: str, config: dict[str, Any]) -> None:
        from rest_framework.exceptions import ValidationError  # noqa: PLC0415

        with self.assertRaises(ValidationError):
            validate_widget_config(SURVEY_RESULTS_WIDGET_TYPE, config)


class TestSurveyResultsWidgetRunner(APIBaseTest):
    def _create_survey(self, *, name: str = "Feedback", archived: bool = False) -> Survey:
        return Survey.objects.create(
            team=self.team,
            name=name,
            type="popover",
            archived=archived,
            created_by=self.user,
            questions=[{"type": "open", "id": "q1", "question": "What can we improve?"}],
        )

    def test_returns_needs_configuration_when_no_survey_selected(self) -> None:
        result = run_survey_results_widget(self.team, {}, user=self.user)

        assert result == {
            "survey": None,
            "responses": [],
            "needsConfiguration": True,
            "hasSurveys": False,
        }

    def test_needs_configuration_reports_existing_surveys(self) -> None:
        self._create_survey()
        result = run_survey_results_widget(self.team, {}, user=self.user)

        assert result["needsConfiguration"] is True
        assert result["hasSurveys"] is True

    def test_archived_surveys_do_not_count_as_existing(self) -> None:
        self._create_survey(archived=True)
        result = run_survey_results_widget(self.team, {}, user=self.user)

        assert result["hasSurveys"] is False

    def test_returns_not_found_for_missing_survey(self) -> None:
        result = run_survey_results_widget(
            self.team, {"surveyId": "00000000-0000-0000-0000-000000000000"}, user=self.user
        )

        assert result == {"survey": None, "responses": [], "surveyNotFound": True}

    def test_returns_not_found_for_other_team_survey(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        survey = Survey.objects.create(team=other_team, name="Other team", type="popover", created_by=self.user)

        result = run_survey_results_widget(self.team, {"surveyId": str(survey.id)}, user=self.user)

        assert result == {"survey": None, "responses": [], "surveyNotFound": True}

    def test_returns_not_found_for_survey_the_user_cannot_access(self) -> None:
        survey = self._create_survey()
        member = User.objects.create_and_join(self.organization, "member@example.test", "pw")
        _block_survey_for_member(self.team, survey, member)

        result = run_survey_results_widget(self.team, {"surveyId": str(survey.id)}, user=member)

        assert result == {"survey": None, "responses": [], "surveyNotFound": True}
