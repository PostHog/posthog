from posthog.models import Survey, Organization, Team, User, FeatureFlag
from django.test import TestCase
from datetime import timedelta, datetime
from django.utils.timezone import now
from posthog.test.base import ClickhouseTestMixin
from posthog.tasks.update_survey_iteration import update_survey_iteration
from posthog.constants import CreationContext


class TestUpdateSurveyIteration(TestCase, ClickhouseTestMixin):
    def setUp(self) -> None:
        super().setUp()

        self.org = Organization.objects.create(name="Org 1")
        self.team = Team.objects.create(organization=self.org, name="My Team")
        self.user = User.objects.create_and_join(self.org, "a@b.c", password=None)
        self.flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="flag_name",
            filters={},
            rollout_percentage=100,
        )

        self.iteration_frequency_days = 60

        self.recurring_survey = Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Popover survey",
            type="popover",
            questions=[{"type": "open", "question": "What's a survey?"}],
            start_date=datetime.now() - timedelta(days=61),
            iteration_count=3,
            iteration_frequency_days=self.iteration_frequency_days,
        )
        self.recurring_survey.internal_targeting_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            active=True,
            key="internal-targeting-flag",
        )

    def test_can_update_survey_iteration(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        self.assertEqual(self.recurring_survey.current_iteration, 1)
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        self.assertEqual(self.recurring_survey.current_iteration, 3)

    def test_can_guard_for_current_survey_iteration_overflow(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        self.assertEqual(self.recurring_survey.current_iteration, 1)
        self.recurring_survey.iteration_frequency_days = 0
        self.recurring_survey.save()
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        self.assertIsNone(self.recurring_survey.current_iteration)

    def test_can_update_internal_targeting_flag(self) -> None:
        # expected_targeting_filters =
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        self.assertEqual(self.recurring_survey.current_iteration, 1)
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        self.assertEqual(self.recurring_survey.current_iteration, 3)

        self.assertDictContainsSubset(
            {
                "groups": [
                    {
                        "variant": "",
                        "properties": [
                            {
                                "key": f"$survey_dismissed/{self.recurring_survey.id}/3",
                                "type": "person",
                                "value": "is_not_set",
                                "operator": "is_not_set",
                            },
                            {
                                "key": f"$survey_responded/{self.recurring_survey.id}/3",
                                "type": "person",
                                "value": "is_not_set",
                                "operator": "is_not_set",
                            },
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
            self.recurring_survey.internal_targeting_flag.filters,
        )

    def test_can_create_internal_targeting_flag(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        self.assertEqual(self.recurring_survey.current_iteration, 1)
        self.recurring_survey.internal_targeting_flag = None
        self.recurring_survey.save()
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        self.assertEqual(self.recurring_survey.current_iteration, 3)

        internal_flag = FeatureFlag.objects.get(key=self.recurring_survey.id)
        assert internal_flag is not None
        if internal_flag is not None:
            self.assertDictContainsSubset(
                {
                    "groups": [
                        {
                            "variant": "",
                            "properties": [
                                {
                                    "key": f"$survey_dismissed/{self.recurring_survey.id}/3",
                                    "type": "person",
                                    "value": "is_not_set",
                                    "operator": "is_not_set",
                                },
                                {
                                    "key": f"$survey_responded/{self.recurring_survey.id}/3",
                                    "type": "person",
                                    "value": "is_not_set",
                                    "operator": "is_not_set",
                                },
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
                internal_flag.filters,
            )

    def test_creation_context_is_set_to_surveys(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        self.assertEqual(self.recurring_survey.current_iteration, 1)
        self.recurring_survey.internal_targeting_flag = None
        self.recurring_survey.save()

        update_survey_iteration()
        self.recurring_survey.refresh_from_db()

        # The internal targeting flag should have been created
        internal_flag = FeatureFlag.objects.get(key=self.recurring_survey.id)
        self.assertIsNotNone(internal_flag)
        self.assertEqual(internal_flag.creation_context, CreationContext.SURVEYS)
