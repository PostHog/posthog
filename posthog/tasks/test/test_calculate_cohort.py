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
    increment_version_and_enqueue_calculate_cohort,
    MAX_AGE_MINUTES,
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

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_nested_cohorts(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            # Create leaf cohort A
            cohort_a = Cohort.objects.create(
                team=self.team,
                name="Cohort A",
                groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
                is_static=False,
            )

            # Create cohort B that depends on cohort A
            cohort_b = Cohort.objects.create(
                team=self.team,
                name="Cohort B",
                groups=[{"properties": [{"key": "id", "value": cohort_a.id, "type": "cohort"}]}],
                is_static=False,
            )

            # Create cohort C that depends on cohort B
            cohort_c = Cohort.objects.create(
                team=self.team,
                name="Cohort C",
                groups=[{"properties": [{"key": "id", "value": cohort_b.id, "type": "cohort"}]}],
                is_static=False,
            )

            # Mock chain application
            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            # Mock task signatures
            mock_task_a = MagicMock()
            mock_task_b = MagicMock()
            mock_task_c = MagicMock()
            mock_calculate_cohort_ch_si.side_effect = [mock_task_a, mock_task_b, mock_task_c]

            # Call the function with cohort C (which has dependencies)
            increment_version_and_enqueue_calculate_cohort(cohort_c, initiating_user=None)

            # Verify that all cohorts have their versions incremented and are marked as calculating
            cohort_a.refresh_from_db()
            cohort_b.refresh_from_db()
            cohort_c.refresh_from_db()

            self.assertEqual(cohort_a.pending_version, 1)
            self.assertEqual(cohort_b.pending_version, 1)
            self.assertEqual(cohort_c.pending_version, 1)
            self.assertTrue(cohort_a.is_calculating)
            self.assertTrue(cohort_b.is_calculating)
            self.assertTrue(cohort_c.is_calculating)

            # Verify that calculate_cohort_ch.si was called for each cohort in the correct order
            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 3)

            # Check that tasks were created with correct arguments (order: A, B, C)
            expected_calls = [
                call(cohort_a.id, 1, None),
                call(cohort_b.id, 1, None),
                call(cohort_c.id, 1, None),
            ]
            mock_calculate_cohort_ch_si.assert_has_calls(expected_calls)

            # Verify that chain was called with the tasks in the correct order
            mock_chain.assert_called_once_with(mock_task_a, mock_task_b, mock_task_c)

            # Verify that the chain was applied async
            mock_chain_instance.apply_async.assert_called_once()

    return TestCalculateCohort
