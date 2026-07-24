from datetime import datetime, timedelta

from posthog.test.base import ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils.timezone import now

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.tasks.update_survey_iteration import update_survey_iteration

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.surveys.backend.models import Survey


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

    def test_survey_ends_after_final_iteration(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(days=self.iteration_frequency_days * 3 + 1)
        self.recurring_survey.save()
        self.assertEqual(self.recurring_survey.current_iteration, 1)
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        self.assertIsNotNone(self.recurring_survey.end_date)
        self.assertEqual(self.recurring_survey.current_iteration, 1)

    def test_survey_end_after_final_iteration_is_logged_as_system_activity(self) -> None:
        self.recurring_survey.start_date = now() - timedelta(days=self.iteration_frequency_days * 3 + 1)
        self.recurring_survey.save()
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()

        log = ActivityLog.objects.get(scope="Survey", item_id=str(self.recurring_survey.id), activity="updated")
        # No user: the scheduler closed it, so the activity log shows it as a system action.
        self.assertTrue(log.is_system)
        self.assertIsNone(log.user)
        # end_date going None -> value is what the frontend renders as "stopped".
        assert log.detail is not None
        change = log.detail["changes"][0]
        self.assertEqual(change["field"], "end_date")
        self.assertEqual(change["action"], "created")
        self.assertIsNotNone(change["after"])

    def test_huge_iteration_frequency_does_not_crash_task(self) -> None:
        self.recurring_survey.iteration_count = 1
        self.recurring_survey.iteration_frequency_days = 2_147_483_647
        self.recurring_survey.save()
        update_survey_iteration()
        self.recurring_survey.refresh_from_db()
        self.assertIsNone(self.recurring_survey.end_date)

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
        assert self.recurring_survey.internal_targeting_flag is not None

        self.assertEqual(self.recurring_survey.internal_targeting_flag.filters, self._expected_iteration_filters(3))

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
        self.assertEqual(internal_flag.filters, self._expected_iteration_filters(3))

    def test_iteration_change_updates_flag_with_new_iteration_suffix(self) -> None:
        """Test that when iteration changes, the flag is updated with the NEW iteration suffix.

        This guards against a merge order bug where old filters could overwrite new ones.
        """
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()
        self.assertEqual(self.recurring_survey.current_iteration, 1)

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
        self.assertEqual(self.recurring_survey.current_iteration, 3)

        # Verify flag now has NEW iteration suffix (/3), not old (/1), and that
        # nothing else was added or dropped on the way through the flag facade
        assert self.recurring_survey.internal_targeting_flag is not None
        self.recurring_survey.internal_targeting_flag.refresh_from_db()
        flag_filters = self.recurring_survey.internal_targeting_flag.filters

        self.assertEqual(flag_filters, self._expected_iteration_filters(3))

    def _expected_iteration_filters(self, iteration: int) -> dict:
        # aggregation_group_type_index (None = person-aggregated) is normalized onto
        # every condition set by the flag serializer on the way through the facade
        return {
            "groups": [
                {
                    "variant": "",
                    "rollout_percentage": 100,
                    "aggregation_group_type_index": None,
                    "properties": [
                        {
                            "key": f"$survey_dismissed/{self.recurring_survey.id}/{iteration}",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                            "type": "person",
                        },
                        {
                            "key": f"$survey_responded/{self.recurring_survey.id}/{iteration}",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                            "type": "person",
                        },
                    ],
                }
            ],
            "aggregation_group_type_index": None,
        }

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_flag_update_is_system_write_and_skips_approval_gate(self, _mock_enabled: MagicMock) -> None:
        self.org.available_product_features = [{"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}]
        self.org.save()
        ApprovalPolicy.objects.create(
            organization=self.org,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        self.recurring_survey.created_by = None
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()

        with self.captureOnCommitCallbacks(execute=True):
            update_survey_iteration()

        self.recurring_survey.refresh_from_db()
        flag = self.recurring_survey.internal_targeting_flag
        assert flag is not None
        self.assertEqual(flag.filters, self._expected_iteration_filters(3))
        self.assertFalse(ChangeRequest.objects.filter(team=self.team).exists())
        log = ActivityLog.objects.get(scope="FeatureFlag", item_id=str(flag.id), activity="updated")
        self.assertTrue(log.is_system)
        self.assertIsNone(log.user)

    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_flag_create_is_system_write_and_skips_approval_gate(self, _mock_enabled: MagicMock) -> None:
        self.org.available_product_features = [{"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}]
        self.org.save()
        ApprovalPolicy.objects.create(
            organization=self.org,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        self.recurring_survey.internal_targeting_flag = None
        self.recurring_survey.start_date = now() - timedelta(self.iteration_frequency_days * 3)
        self.recurring_survey.save()

        with self.captureOnCommitCallbacks(execute=True):
            update_survey_iteration()

        internal_flag = FeatureFlag.objects.get(key=self.recurring_survey.id)
        # System write, but attribution is restored so the creator keeps flag access
        self.assertEqual(internal_flag.created_by, self.user)
        self.assertTrue(internal_flag.active)
        self.assertEqual(internal_flag.filters, self._expected_iteration_filters(3))
        self.assertFalse(ChangeRequest.objects.filter(team=self.team).exists())
        log = ActivityLog.objects.get(scope="FeatureFlag", item_id=str(internal_flag.id), activity="created")
        self.assertTrue(log.is_system)
        self.assertIsNone(log.user)
