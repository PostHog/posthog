from collections.abc import Callable
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from unittest.mock import MagicMock, patch, call

from freezegun import freeze_time

from posthog.models.cohort import Cohort
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import (
    calculate_cohort_from_list,
    enqueue_cohorts_to_calculate,
    MAX_AGE_MINUTES,
    MAX_ERRORS_CALCULATING,
    update_stale_cohort_metrics,
    COHORTS_STALE_COUNT_GAUGE,
    COHORT_STUCK_COUNT_GAUGE,
)
from posthog.test.base import APIBaseTest


def calculate_cohort_test_factory(event_factory: Callable, person_factory: Callable):  # type: ignore
    class TestCalculateCohort(APIBaseTest):
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
        def test_create_stickiness_cohort(self, _calculate_cohort_from_list: MagicMock) -> None:
            person_factory(team_id=self.team.pk, distinct_ids=["blabla"])
            event_factory(
                team=self.team,
                event="$pageview",
                distinct_id="blabla",
                properties={"$math_prop": 1},
                timestamp="2021-01-01T12:00:00Z",
            )
            response = self.client.post(
                f"/api/projects/{self.team.id}/cohorts/?insight=STICKINESS&properties=%5B%5D&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&shown_as=Stickiness&date_from=2021-01-01&entity_id=%24pageview&entity_type=events&stickiness_days=1&label=%24pageview",
                {"name": "test", "is_static": True},
            ).json()

            cohort_id = response["id"]
            _calculate_cohort_from_list.assert_called_once_with(cohort_id, ["blabla"])
            calculate_cohort_from_list(cohort_id, ["blabla"])
            cohort = Cohort.objects.get(pk=cohort_id)
            people = Person.objects.filter(cohort__id=cohort.pk)
            self.assertEqual(people.count(), 1)

        @patch("posthog.tasks.calculate_cohort.calculate_cohort_from_list.delay")
        def test_create_trends_cohort(self, _calculate_cohort_from_list: MagicMock) -> None:
            person_factory(team_id=self.team.pk, distinct_ids=["blabla"])
            with freeze_time("2021-01-01 00:06:34"):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="blabla",
                    properties={"$math_prop": 1},
                    timestamp="2021-01-01T12:00:00Z",
                )

            with freeze_time("2021-01-02 00:06:34"):
                event_factory(
                    team=self.team,
                    event="$pageview",
                    distinct_id="blabla",
                    properties={"$math_prop": 4},
                    timestamp="2021-01-01T12:00:00Z",
                )

            response = self.client.post(
                f"/api/projects/{self.team.id}/cohorts/?interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&properties=%5B%5D&entity_id=%24pageview&entity_type=events&date_from=2021-01-01&date_to=2021-01-01&label=%24pageview",
                {"name": "test", "is_static": True},
            ).json()
            cohort_id = response["id"]
            _calculate_cohort_from_list.assert_called_once_with(cohort_id, ["blabla"])
            calculate_cohort_from_list(cohort_id, ["blabla"])
            cohort = Cohort.objects.get(pk=cohort_id)
            people = Person.objects.filter(cohort__id=cohort.pk)
            self.assertEqual(people.count(), 1)

        @patch("posthog.tasks.calculate_cohort.increment_version_and_enqueue_calculate_cohort")
        def test_exponential_backoff(self, patch_increment_version_and_enqueue_calculate_cohort: MagicMock) -> None:
            # Exponential backoff
            Cohort.objects.create(
                last_calculation=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1),
                errors_calculating=1,
                last_error_at=timezone.now() - relativedelta(minutes=60),  # Should be included
                team_id=self.team.pk,
            )
            Cohort.objects.create(
                last_calculation=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1),
                errors_calculating=5,
                last_error_at=timezone.now() - relativedelta(minutes=60),  # Should be excluded
                team_id=self.team.pk,
            )
            # Test empty last_error_at
            Cohort.objects.create(
                last_calculation=timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1),
                errors_calculating=1,
                team_id=self.team.pk,
            )
            enqueue_cohorts_to_calculate(5)
            self.assertEqual(patch_increment_version_and_enqueue_calculate_cohort.call_count, 2)

        @patch.object(COHORTS_STALE_COUNT_GAUGE, "labels")
        def test_update_stale_cohort_metrics(self, mock_labels: MagicMock) -> None:
            mock_gauge = MagicMock()
            mock_labels.return_value = mock_gauge

            now = timezone.now()

            # Create cohorts with different staleness levels
            Cohort.objects.create(
                team_id=self.team.pk,
                name="fresh_cohort",
                last_calculation=now - relativedelta(hours=12),  # Not stale
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="stale_24h",
                last_calculation=now - relativedelta(hours=30),  # Stale for 24h
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="stale_36h",
                last_calculation=now - relativedelta(hours=40),  # Stale for 36h
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="stale_48h",
                last_calculation=now - relativedelta(hours=50),  # Stale for 48h
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            # Create cohorts that should be excluded
            Cohort.objects.create(
                team_id=self.team.pk,
                name="null_last_calc",  # Should be excluded
                last_calculation=None,
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="deleted_cohort",
                last_calculation=now - relativedelta(hours=50),
                deleted=True,  # Should be excluded
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="static_cohort",
                last_calculation=now - relativedelta(hours=50),
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=True,  # Should be excluded
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="high_errors",
                last_calculation=now - relativedelta(hours=50),
                deleted=False,
                is_calculating=False,
                errors_calculating=MAX_ERRORS_CALCULATING + 1,  # Should be excluded (>20 errors)
                is_static=False,
            )

            update_stale_cohort_metrics()

            mock_labels.assert_any_call(hours="24")
            mock_labels.assert_any_call(hours="36")
            mock_labels.assert_any_call(hours="48")

            set_calls = mock_gauge.set.call_args_list
            self.assertEqual(len(set_calls), 3)

            self.assertEqual(set_calls[0][0][0], 3)  # 24h: stale_24h, stale_36h, stale_48h
            self.assertEqual(set_calls[1][0][0], 2)  # 36h: stale_36h, stale_48h
            self.assertEqual(set_calls[2][0][0], 1)  # 48h: stale_48h

        @patch.object(COHORT_STUCK_COUNT_GAUGE, "set")
        def test_stuck_cohort_metrics(self, mock_set: MagicMock) -> None:
            now = timezone.now()

            # Create stuck cohort - is_calculating=True and last_calculation > 12 hours ago
            Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort",
                last_calculation=now - relativedelta(hours=2),
                deleted=False,
                is_calculating=True,  # Stuck calculating
                errors_calculating=5,
                is_static=False,
            )

            # Create another stuck cohort
            Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort_2",
                last_calculation=now - relativedelta(hours=3),
                deleted=False,
                is_calculating=True,  # Stuck calculating
                errors_calculating=2,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="not_calculating",
                last_calculation=now - relativedelta(hours=24),  # Old but not calculating
                deleted=False,
                is_calculating=False,  # Not calculating
                errors_calculating=0,
                is_static=False,
            )

            Cohort.objects.create(
                team_id=self.team.pk,
                name="recent_calculation",
                last_calculation=now - relativedelta(minutes=59),  # Recent calculation
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            update_stale_cohort_metrics()
            mock_set.assert_called_with(2)

        @patch("posthog.tasks.calculate_cohort.increment_version_and_enqueue_calculate_cohort")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_enqueue_cohorts_logs_correctly(self, mock_logger: MagicMock, mock_increment: MagicMock) -> None:
            # Create cohorts that will be selected for calculation
            last_calc_time = timezone.now() - relativedelta(minutes=MAX_AGE_MINUTES + 1)
            cohort1 = Cohort.objects.create(
                team_id=self.team.pk,
                name="test_cohort_1",
                last_calculation=last_calc_time,
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )
            cohort2 = Cohort.objects.create(
                team_id=self.team.pk,
                name="test_cohort_2",
                last_calculation=None,  # Never calculated
                deleted=False,
                is_calculating=False,
                errors_calculating=0,
                is_static=False,
            )

            enqueue_cohorts_to_calculate(2)

            # Verify the log was called for both cohorts
            self.assertEqual(mock_logger.info.call_count, 2)

            # Check the log calls have the expected format
            self.assertCountEqual(
                mock_logger.info.call_args_list,
                [
                    call("Enqueuing cohort calculation", cohort_id=cohort2.pk, last_calculation=None),
                    call("Enqueuing cohort calculation", cohort_id=cohort1.pk, last_calculation=last_calc_time),
                ],
            )

    return TestCalculateCohort
