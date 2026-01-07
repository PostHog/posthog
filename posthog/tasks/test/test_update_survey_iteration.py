from datetime import datetime, timedelta

from posthog.test.base import ClickhouseTestMixin

from django.test import TestCase
from django.utils.timezone import now

from posthog.models import FeatureFlag, Organization, Survey, Team, User
from posthog.tasks.update_survey_iteration import update_survey_iteration


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
        assert self.recurring_survey.current_iteration == 1
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        assert self.recurring_survey.current_iteration == 3

    def test_can_guard_for_current_survey_iteration_overflow(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        assert self.recurring_survey.current_iteration == 1
        self.recurring_survey.iteration_frequency_days = 0
        self.recurring_survey.save()
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        assert self.recurring_survey.current_iteration is None

    def test_can_update_internal_targeting_flag(self) -> None:
        # expected_targeting_filters =
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        assert self.recurring_survey.current_iteration == 1
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        assert self.recurring_survey.current_iteration == 3

        assert {
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
        }.items() <= self.recurring_survey.internal_targeting_flag.filters.items()

    def test_can_create_internal_targeting_flag(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        assert self.recurring_survey.current_iteration == 1
        self.recurring_survey.internal_targeting_flag = None
        self.recurring_survey.save()
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        assert self.recurring_survey.current_iteration == 3

        internal_flag = FeatureFlag.objects.get(key=self.recurring_survey.id)
        assert internal_flag is not None
        if internal_flag is not None:
            assert {
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
            }.items() <= internal_flag.filters.items()

    def test_iteration_change_updates_flag_with_new_iteration_suffix(self) -> None:
        """Test that when iteration changes, the flag is updated with the NEW iteration suffix.

        This guards against a merge order bug where old filters could overwrite new ones.
        """
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        assert self.recurring_survey.current_iteration == 1

        # Set up flag with OLD iteration suffix (/1)
        old_filters = {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "properties": [
                        {
                            "key": f"$survey_dismissed/{self.recurring_survey.id}/1",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                        {
                            "key": f"$survey_responded/{self.recurring_survey.id}/1",
                            "type": "person",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                    ],
                }
            ]
        }
        assert self.recurring_survey.internal_targeting_flag is not None
        self.recurring_survey.internal_targeting_flag.filters = old_filters
        self.recurring_survey.internal_targeting_flag.save()

        # Run the job - should update to iteration 3
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        assert self.recurring_survey.current_iteration == 3

        # Verify flag now has NEW iteration suffix (/3), not old (/1)
        assert self.recurring_survey.internal_targeting_flag is not None
        self.recurring_survey.internal_targeting_flag.refresh_from_db()
        flag_filters = self.recurring_survey.internal_targeting_flag.filters
        properties = flag_filters["groups"][0]["properties"]
        property_keys = [p["key"] for p in properties]

        assert f"$survey_dismissed/{self.recurring_survey.id}/3" in property_keys
        assert f"$survey_responded/{self.recurring_survey.id}/3" in property_keys
        assert f"$survey_dismissed/{self.recurring_survey.id}/1" not in property_keys
        assert f"$survey_responded/{self.recurring_survey.id}/1" not in property_keys
