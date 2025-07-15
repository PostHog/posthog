from collections.abc import Callable
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from unittest.mock import MagicMock, patch

from freezegun import freeze_time

from posthog.models.cohort import Cohort
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import (
    calculate_cohort_from_list,
    enqueue_cohorts_to_calculate,
    MAX_AGE_MINUTES,
    MAX_ERRORS_CALCULATING,
    MAX_STUCK_COHORTS_TO_RESET,
    reset_stuck_cohorts,
    update_cohort_metrics,
    COHORTS_STALE_COUNT_GAUGE,
    COHORT_STUCK_COUNT_GAUGE,
    increment_version_and_enqueue_calculate_cohort,
)
from posthog.test.base import APIBaseTest

MISSING_COHORT_ID = 12345


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

            update_cohort_metrics()

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

            update_cohort_metrics()
            mock_set.assert_called_with(2)

        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_cohorts(self, mock_logger: MagicMock) -> None:
            now = timezone.now()

            # Create stuck cohorts that should be reset (is_calculating=True, last_calculation > 24 hours ago)
            stuck_cohort_1 = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort_1",
                last_calculation=now - relativedelta(hours=25),  # Stuck for 25 hours
                deleted=False,
                is_calculating=True,
                errors_calculating=2,
                is_static=False,
            )

            stuck_cohort_2 = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_cohort_2",
                last_calculation=now - relativedelta(hours=48),  # Stuck for 48 hours
                deleted=False,
                is_calculating=True,
                errors_calculating=1,
                is_static=False,
            )

            # Create cohorts that should NOT be reset
            # Not stuck (recent calculation)
            not_stuck_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="not_stuck_cohort",
                last_calculation=now - relativedelta(minutes=10),  # Recent calculation
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            # Static cohort (should be excluded)
            static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="static_cohort",
                last_calculation=now - relativedelta(hours=48),
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,  # Static cohorts are excluded
            )

            # Deleted cohort (should be excluded)
            deleted_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="deleted_cohort",
                last_calculation=now - relativedelta(hours=48),
                deleted=True,  # Deleted cohorts are excluded
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            # Cohort with null last_calculation (should be excluded)
            null_last_calc_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="null_last_calc_cohort",
                last_calculation=None,  # Null last_calculation is excluded
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=False,
            )

            # Not calculating cohort (should be excluded)
            not_calculating_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="not_calculating_cohort",
                last_calculation=now - relativedelta(hours=48),
                deleted=False,
                is_calculating=False,  # Not calculating
                errors_calculating=0,
                is_static=False,
            )

            # Run the function
            reset_stuck_cohorts()

            # Verify that stuck cohorts were reset
            stuck_cohort_1.refresh_from_db()
            stuck_cohort_2.refresh_from_db()
            self.assertFalse(stuck_cohort_1.is_calculating)
            self.assertFalse(stuck_cohort_2.is_calculating)

            # Verify that non-stuck cohorts were NOT reset
            not_stuck_cohort.refresh_from_db()
            static_cohort.refresh_from_db()
            deleted_cohort.refresh_from_db()
            null_last_calc_cohort.refresh_from_db()
            not_calculating_cohort.refresh_from_db()

            self.assertTrue(not_stuck_cohort.is_calculating)  # Should still be calculating
            self.assertTrue(static_cohort.is_calculating)  # Should still be calculating
            self.assertTrue(deleted_cohort.is_calculating)  # Should still be calculating
            self.assertTrue(null_last_calc_cohort.is_calculating)  # Should still be calculating
            self.assertFalse(not_calculating_cohort.is_calculating)  # Should remain not calculating

            # Verify logging
            mock_logger.warning.assert_called_once()
            args, kwargs = mock_logger.warning.call_args
            self.assertEqual(args[0], "reset_stuck_cohorts")
            self.assertEqual(set(kwargs["cohort_ids"]), {stuck_cohort_1.pk, stuck_cohort_2.pk})
            self.assertEqual(kwargs["count"], 2)

        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_cohorts_respects_limit(self, mock_logger: MagicMock) -> None:
            now = timezone.now()

            # Create more stuck cohorts than the limit (MAX_STUCK_COHORTS_TO_RESET)
            stuck_cohorts = []
            for i in range(MAX_STUCK_COHORTS_TO_RESET + 3):
                cohort = Cohort.objects.create(
                    team_id=self.team.pk,
                    name=f"stuck_cohort_{i}",
                    last_calculation=now - relativedelta(hours=25),
                    deleted=False,
                    is_calculating=True,
                    errors_calculating=0,
                    is_static=False,
                )
                stuck_cohorts.append(cohort)

            reset_stuck_cohorts()

            # Count how many were actually reset
            reset_count = 0
            for cohort in stuck_cohorts:
                cohort.refresh_from_db()
                if not cohort.is_calculating:
                    reset_count += 1

            self.assertEqual(reset_count, MAX_STUCK_COHORTS_TO_RESET)

            # Verify logging
            mock_logger.warning.assert_called_once()
            args, kwargs = mock_logger.warning.call_args
            self.assertEqual(args[0], "reset_stuck_cohorts")
            self.assertEqual(len(kwargs["cohort_ids"]), MAX_STUCK_COHORTS_TO_RESET)
            self.assertEqual(kwargs["count"], MAX_STUCK_COHORTS_TO_RESET)

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

            self.assertEqual(mock_logger.warning.call_count, 1)
            args, kwargs = mock_logger.warning.call_args
            assert args[0] == "enqueued_cohort_calculation"
            assert set(kwargs["cohort_ids"]) == {cohort1.pk, cohort2.pk}

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_nested_cohorts(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            # Test dependency graph structure:
            # A ──┐
            #     ├─→ C ──→ D
            # B ──┘
            # Expected execution order: A, B, C, D

            # Create leaf cohort A
            cohort_a = Cohort.objects.create(
                team=self.team,
                name="Cohort A",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [{"key": "$some_prop_a", "value": "something_a", "type": "person"}],
                    }
                },
                is_static=False,
            )

            # Create leaf cohort B
            cohort_b = Cohort.objects.create(
                team=self.team,
                name="Cohort B",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [{"key": "$some_prop_b", "value": "something_b", "type": "person"}],
                    }
                },
                is_static=False,
            )

            # Create cohort C that depends on both cohort A and B
            cohort_c = Cohort.objects.create(
                team=self.team,
                name="Cohort C",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": cohort_a.id, "type": "cohort"},
                            {"key": "id", "value": cohort_b.id, "type": "cohort"},
                        ],
                    }
                },
                is_static=False,
            )

            # Create cohort D that depends on cohort C
            cohort_d = Cohort.objects.create(
                team=self.team,
                name="Cohort D",
                filters={
                    "properties": {"type": "AND", "values": [{"key": "id", "value": cohort_c.id, "type": "cohort"}]}
                },
                is_static=False,
            )

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(cohort_d, initiating_user=None)

            # Verify that all cohorts have their versions incremented and are marked as calculating
            cohort_a.refresh_from_db()
            cohort_b.refresh_from_db()
            cohort_c.refresh_from_db()
            cohort_d.refresh_from_db()

            self.assertEqual(cohort_a.pending_version, 1)
            self.assertEqual(cohort_b.pending_version, 1)
            self.assertEqual(cohort_c.pending_version, 1)
            self.assertEqual(cohort_d.pending_version, 1)
            self.assertTrue(cohort_a.is_calculating)
            self.assertTrue(cohort_b.is_calculating)
            self.assertTrue(cohort_c.is_calculating)
            self.assertTrue(cohort_d.is_calculating)

            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 4)

            # Extract the actual call order and verify dependency constraints are satisfied
            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]  # Extract cohort IDs

            self.assertEqual(set(actual_cohort_order), {cohort_a.id, cohort_b.id, cohort_c.id, cohort_d.id})

            # Verify dependency constraints:
            # Both A and B (leaf nodes) must come before C
            a_index = actual_cohort_order.index(cohort_a.id)
            b_index = actual_cohort_order.index(cohort_b.id)
            c_index = actual_cohort_order.index(cohort_c.id)
            d_index = actual_cohort_order.index(cohort_d.id)

            self.assertLess(a_index, c_index, "Cohort A must be processed before C (dependency)")
            self.assertLess(b_index, c_index, "Cohort B must be processed before C (dependency)")
            self.assertLess(c_index, d_index, "Cohort C must be processed before D (dependency)")

            mock_chain.assert_called_once_with(mock_task, mock_task, mock_task, mock_task)
            mock_chain_instance.apply_async.assert_called_once()

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_missing_cohort(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            cohort_a = Cohort.objects.create(
                team=self.team,
                name="Cohort A",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [{"key": "$some_prop_a", "value": "something_a", "type": "person"}],
                    }
                },
                is_static=False,
            )

            # Create a cohort that references a non-existent cohort ID
            cohort_with_missing_dependency = Cohort.objects.create(
                team=self.team,
                name="Cohort with missing dependency",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": MISSING_COHORT_ID, "type": "cohort"},  # non-existent cohort
                            {"key": "id", "value": cohort_a.id, "type": "cohort"},
                            {"key": "$some_prop", "value": "something", "type": "person"},
                        ],
                    }
                },
                is_static=False,
            )

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(cohort_with_missing_dependency, initiating_user=None)

            # Verify the cohort was still processed despite missing dependency
            cohort_with_missing_dependency.refresh_from_db()
            cohort_a.refresh_from_db()
            self.assertEqual(cohort_with_missing_dependency.pending_version, 1)
            self.assertEqual(cohort_a.pending_version, 1)
            self.assertTrue(cohort_with_missing_dependency.is_calculating)
            self.assertTrue(cohort_a.is_calculating)

            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 2)

            # Extract the actual call order and verify dependency cohort comes first
            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]  # Extract cohort IDs
            expected_cohort_order = [cohort_a.id, cohort_with_missing_dependency.id]

            self.assertEqual(
                actual_cohort_order,
                expected_cohort_order,
                "Dependency cohort A should be processed before cohort with missing dependency",
            )

            mock_chain.assert_called_once_with(mock_task, mock_task)
            mock_chain_instance.apply_async.assert_called_once()

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_static_dependencies(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            static_cohort_a = Cohort.objects.create(
                team=self.team,
                name="Static Cohort A",
                is_static=True,
            )

            dynamic_cohort = Cohort.objects.create(
                team=self.team,
                name="Dynamic Cohort depending on static cohorts",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": static_cohort_a.id, "type": "cohort"},
                            {"key": "$dynamic_prop", "value": "dynamic_value", "type": "person"},
                        ],
                    }
                },
                is_static=False,
            )

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(dynamic_cohort, initiating_user=None)

            static_cohort_a.refresh_from_db()
            dynamic_cohort.refresh_from_db()

            self.assertEqual(static_cohort_a.pending_version, None)
            self.assertFalse(static_cohort_a.is_calculating)

            self.assertEqual(dynamic_cohort.pending_version, 1)
            self.assertTrue(dynamic_cohort.is_calculating)

            # Only one task should be created (for the dynamic cohort)
            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 1)

            # Verify the dynamic cohort was called
            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]
            expected_cohort_order = [dynamic_cohort.id]

            self.assertEqual(
                actual_cohort_order,
                expected_cohort_order,
                "Only the dynamic cohort should be processed, static dependencies are skipped",
            )

            mock_chain.assert_called_once_with(mock_task)
            mock_chain_instance.apply_async.assert_called_once()

        @patch("posthog.tasks.calculate_cohort.chain")
        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
        def test_increment_version_and_enqueue_calculate_cohort_with_cyclic_dependency(
            self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
        ) -> None:
            # Create a cyclic dependency: A -> B -> C -> A
            cohort_a = Cohort.objects.create(
                team=self.team,
                name="Cohort A",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [{"key": "$some_prop_a", "value": "something_a", "type": "person"}],
                    }
                },
                is_static=False,
            )

            cohort_b = Cohort.objects.create(
                team=self.team,
                name="Cohort B",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": cohort_a.id, "type": "cohort"},
                            {"key": "$some_prop_b", "value": "something_b", "type": "person"},
                        ],
                    }
                },
                is_static=False,
            )

            cohort_c = Cohort.objects.create(
                team=self.team,
                name="Cohort C",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "id", "value": cohort_b.id, "type": "cohort"},
                            {"key": "$some_prop_c", "value": "something_c", "type": "person"},
                        ],
                    }
                },
                is_static=False,
            )

            # Create the cycle by making A depend on C
            cohort_a.filters = {
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort_c.id, "type": "cohort"},
                        {"key": "$some_prop_a", "value": "something_a", "type": "person"},
                    ],
                }
            }
            cohort_a.save()

            mock_chain_instance = MagicMock()
            mock_chain.return_value = mock_chain_instance

            mock_task = MagicMock()
            mock_calculate_cohort_ch_si.return_value = mock_task

            increment_version_and_enqueue_calculate_cohort(cohort_a, initiating_user=None)

            cohort_a.refresh_from_db()
            cohort_b.refresh_from_db()
            cohort_c.refresh_from_db()

            self.assertEqual(cohort_a.pending_version, 1)
            self.assertEqual(cohort_b.pending_version, 1)
            self.assertEqual(cohort_c.pending_version, 1)
            self.assertTrue(cohort_a.is_calculating)
            self.assertTrue(cohort_b.is_calculating)
            self.assertTrue(cohort_c.is_calculating)

            self.assertEqual(mock_calculate_cohort_ch_si.call_count, 3)

            actual_calls = mock_calculate_cohort_ch_si.call_args_list
            actual_cohort_order = [call[0][0] for call in actual_calls]

            self.assertEqual(len(actual_cohort_order), 3)
            self.assertEqual(len(set(actual_cohort_order)), 3)

            mock_chain.assert_called_once_with(mock_task, mock_task, mock_task)
            mock_chain_instance.apply_async.assert_called_once()

    return TestCalculateCohort
