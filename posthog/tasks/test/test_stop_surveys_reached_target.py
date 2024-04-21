from posthog.models import Survey, Organization, Team, User, FeatureFlag
from django.test import TestCase
from dateutil.relativedelta import relativedelta
from datetime import timedelta
from django.utils.timezone import now
from posthog.test.base import _create_event, flush_persons_and_events, ClickhouseTestMixin
from posthog.tasks.stop_surveys_reached_target import stop_surveys_reached_target


class TestStopSurveysReachedTarget(TestCase, ClickhouseTestMixin):
    def setUp(self) -> None:
        super().setUp()

        self.org = Organization.objects.create(name="Org 1")
        self.team1 = Team.objects.create(organization=self.org, name="Team 1")
        self.team2 = Team.objects.create(organization=self.org, name="Team 2")
        self.user = User.objects.create_and_join(self.org, "a@b.c", password=None)
        self.flag = FeatureFlag.objects.create(
            team=self.team1,
            created_by=self.user,
            key="flag_name",
            filters={},
            rollout_percentage=100,
        )

    def _create_event_for_survey(self, survey: Survey, event: str = "survey sent") -> None:
        _create_event(
            distinct_id="0",
            event=event,
            properties={
                "$survey_id": str(survey.id),
            },
            timestamp=now(),
            team=survey.team,
        )

    def test_stop_surveys_with_enough_responses(self) -> None:
        surveys = [
            Survey.objects.create(
                name="1",
                team=self.team1,
                created_by=self.user,
                linked_flag=self.flag,
                responses_limit=1,
                created_at=now() - relativedelta(hours=12),
            ),
            Survey.objects.create(
                name="2",
                team=self.team1,
                created_by=self.user,
                linked_flag=self.flag,
                responses_limit=1,
                created_at=now() - relativedelta(hours=12),
            ),
            Survey.objects.create(
                name="3",
                team=self.team2,
                created_by=self.user,
                linked_flag=self.flag,
                responses_limit=1,
                created_at=now() - relativedelta(hours=12),
            ),
        ]

        for survey in surveys:
            self._create_event_for_survey(survey)

        # Check that having more responses than the limit indicates will stop the survey
        self._create_event_for_survey(surveys[0])

        flush_persons_and_events()

        stop_surveys_reached_target()

        for survey in surveys:
            survey.refresh_from_db()
            assert now() - survey.end_date < timedelta(seconds=1)
            assert not survey.responses_limit

    def test_do_not_stop_survey_with_not_enough_responses(self) -> None:
        survey = Survey.objects.create(
            name="1",
            team=self.team1,
            created_by=self.user,
            linked_flag=self.flag,
            responses_limit=3,
            created_at=now() - relativedelta(hours=12),
        )
        self._create_event_for_survey(survey)
        flush_persons_and_events()

        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert not survey.end_date
        assert survey.responses_limit == 3

    def test_do_not_stop_survey_without_limit(self) -> None:
        survey = Survey.objects.create(
            name="1",
            team=self.team1,
            created_by=self.user,
            linked_flag=self.flag,
            created_at=now() - relativedelta(hours=12),
        )
        self._create_event_for_survey(survey)
        flush_persons_and_events()

        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert not survey.end_date

    def test_do_not_stop_survey_with_other_events(self) -> None:
        survey = Survey.objects.create(
            name="1",
            team=self.team1,
            created_by=self.user,
            linked_flag=self.flag,
            responses_limit=1,
            created_at=now() - relativedelta(hours=12),
        )
        self._create_event_for_survey(survey, event="survey dismissed")
        self._create_event_for_survey(survey, event="survey shown")
        flush_persons_and_events()

        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert not survey.end_date
