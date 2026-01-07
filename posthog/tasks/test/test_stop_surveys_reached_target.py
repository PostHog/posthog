from datetime import datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events, snapshot_clickhouse_queries

from django.test import TestCase
from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.models import FeatureFlag, Organization, Survey, Team, User
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

    def _create_event_for_survey(
        self,
        survey: Survey,
        event: str = "survey sent",
        custom_timestamp: datetime | None = None,
        submission_id: str | None = None,
    ) -> None:
        timestamp = custom_timestamp or now()
        properties: dict = {
            "$survey_id": str(survey.id),
        }
        if submission_id:
            properties["$survey_submission_id"] = submission_id
        _create_event(
            distinct_id="0",
            event=event,
            properties=properties,
            timestamp=timestamp,
            team=survey.team,
        )

    @freeze_time("2022-01-01")
    @snapshot_clickhouse_queries
    def test_stop_surveys_with_enough_responses(self) -> None:
        surveys = [
            Survey.objects.create(
                name="1",
                team=self.team1,
                created_by=self.user,
                linked_flag=self.flag,
                responses_limit=1,
            ),
            Survey.objects.create(
                name="2",
                team=self.team1,
                created_by=self.user,
                linked_flag=self.flag,
                responses_limit=1,
            ),
            Survey.objects.create(
                name="3",
                team=self.team2,
                created_by=self.user,
                linked_flag=self.flag,
                responses_limit=1,
            ),
        ]

        # TRICKY: We can't override created at in the model create because of auto_now_add, so we need to update it manually
        surveys[1].created_at = now() - relativedelta(days=2, hours=4)
        surveys[1].save()

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
            created_at=now(),
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
            created_at=now(),
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
            created_at=now(),
        )
        self._create_event_for_survey(survey, event="survey dismissed")
        self._create_event_for_survey(survey, event="survey shown")
        flush_persons_and_events()

        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert not survey.end_date

    def test_do_not_stop_survey_with_events_before_creation_date(self) -> None:
        survey = Survey.objects.create(
            name="1",
            team=self.team1,
            created_by=self.user,
            linked_flag=self.flag,
            responses_limit=1,
            created_at=now(),
        )
        self._create_event_for_survey(survey, event="survey sent", custom_timestamp=now() - relativedelta(hours=12))
        flush_persons_and_events()

        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert not survey.end_date

    def test_do_not_stop_already_stopped_survey_with_responses_limit(self) -> None:
        survey = Survey.objects.create(
            name="1",
            team=self.team1,
            created_by=self.user,
            linked_flag=self.flag,
            responses_limit=1,
            end_date=now() - relativedelta(hours=1),
        )
        survey.created_at = now() - relativedelta(hours=1)
        survey.save()

        self._create_event_for_survey(survey, event="survey sent")
        flush_persons_and_events()

        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert now() - relativedelta(hours=1) - survey.end_date < timedelta(seconds=1)
        assert survey.responses_limit == 1

    def test_partial_responses_count_as_single_response(self) -> None:
        survey = Survey.objects.create(
            name="1",
            team=self.team1,
            created_by=self.user,
            linked_flag=self.flag,
            responses_limit=3,
            created_at=now(),
        )

        # Create 3 events with the same submission_id (partial responses from one user)
        # These should count as 1 unique response
        self._create_event_for_survey(survey, submission_id="submission-1")
        self._create_event_for_survey(survey, submission_id="submission-1")
        self._create_event_for_survey(survey, submission_id="submission-1")

        # Create 1 more unique response
        self._create_event_for_survey(survey, submission_id="submission-2")

        flush_persons_and_events()

        # Total events = 4, but unique submissions = 2
        # Since 2 < 3 (responses_limit), survey should NOT be stopped
        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert survey.end_date is None
        assert survey.responses_limit == 3

    def test_stop_survey_when_unique_submissions_reach_limit(self) -> None:
        survey = Survey.objects.create(
            name="1",
            team=self.team1,
            created_by=self.user,
            linked_flag=self.flag,
            responses_limit=2,
            created_at=now(),
        )

        # Create multiple partial responses that should count as 2 unique submissions
        self._create_event_for_survey(survey, submission_id="submission-1")
        self._create_event_for_survey(survey, submission_id="submission-1")
        self._create_event_for_survey(survey, submission_id="submission-2")
        self._create_event_for_survey(survey, submission_id="submission-2")
        self._create_event_for_survey(survey, submission_id="submission-2")

        flush_persons_and_events()

        # Total events = 5, but unique submissions = 2
        # Since 2 >= 2 (responses_limit), survey SHOULD be stopped
        stop_surveys_reached_target()

        survey.refresh_from_db()
        assert survey.end_date is not None
        assert survey.responses_limit is None
