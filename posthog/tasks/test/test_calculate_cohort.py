from collections.abc import Callable

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from dateutil.relativedelta import relativedelta
from parameterized import parameterized

from posthog.models.cohort import Cohort
from posthog.models.person import Person
from posthog.tasks.calculate_cohort import (
    COHORT_STUCK_COUNT_GAUGE,
    COHORTS_STALE_COUNT_GAUGE,
    COHORTS_TOTAL_GAUGE,
    MAX_AGE_MINUTES,
    MAX_ERRORS_CALCULATING,
    MAX_STUCK_COHORTS_TO_RESET,
    calculate_cohort_from_list,
    enqueue_cohorts_to_calculate,
    increment_version_and_enqueue_calculate_cohort,
    insert_cohort_from_filters,
    reset_stuck_cohorts,
    update_cohort_metrics,
)

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
            calculate_cohort_from_list(cohort_id, ["blabla"], team_id=self.team.id, id_type="distinct_id")
            cohort = Cohort.objects.get(pk=cohort_id)
            people = Person.objects.filter(cohort__id=cohort.pk, team_id=cohort.team_id)
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
            calculate_cohort_from_list(cohort_id, ["blabla"], team_id=self.team.id, id_type="distinct_id")
            cohort = Cohort.objects.get(pk=cohort_id)
            people = Person.objects.filter(cohort__id=cohort.pk, team_id=cohort.team_id)
            self.assertEqual(people.count(), 1)

        def test_calculate_cohort_from_list_with_person_id_type(self) -> None:
            """Test that calculate_cohort_from_list works correctly with person UUIDs"""
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["user123"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["user456"])

            cohort = Cohort.objects.create(team=self.team, is_static=True, name="test_person_id_cohort")

            # Test with person UUIDs
            calculate_cohort_from_list(
                cohort.id,
                [str(person1.uuid), str(person2.uuid)],
                team_id=self.team.id,
                id_type="person_id",
            )

            # Verify persons were added to cohort
            cohort.refresh_from_db()
            people_in_cohort = Person.objects.filter(cohort__id=cohort.pk, team_id=cohort.team_id)
            self.assertEqual(people_in_cohort.count(), 2)

            # Verify specific persons are in the cohort
            person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
            self.assertIn(str(person1.uuid), person_uuids_in_cohort)
            self.assertIn(str(person2.uuid), person_uuids_in_cohort)

        def test_calculate_cohort_from_list_with_distinct_id_type(self) -> None:
            """Test that calculate_cohort_from_list works correctly with distinct IDs"""
            person1 = person_factory(team_id=self.team.pk, distinct_ids=["user123"])
            person2 = person_factory(team_id=self.team.pk, distinct_ids=["user456"])

            cohort = Cohort.objects.create(team=self.team, is_static=True, name="test_distinct_id_cohort")

            # Test with distinct IDs
            calculate_cohort_from_list(
                cohort.id,
                ["user123", "user456"],
                team_id=self.team.id,
                id_type="distinct_id",
            )

            # Verify persons were added to cohort
            cohort.refresh_from_db()
            people_in_cohort = Person.objects.filter(cohort__id=cohort.pk, team_id=cohort.team_id)
            self.assertEqual(people_in_cohort.count(), 2)

            # Verify specific persons are in the cohort
            person_uuids_in_cohort = {str(p.uuid) for p in people_in_cohort}
            self.assertIn(str(person1.uuid), person_uuids_in_cohort)
            self.assertIn(str(person2.uuid), person_uuids_in_cohort)

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

        @patch.object(COHORTS_TOTAL_GAUGE, "set")
        @patch.object(COHORTS_STALE_COUNT_GAUGE, "labels")
        def test_update_stale_cohort_metrics(self, mock_labels: MagicMock, mock_total_set: MagicMock) -> None:
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

            # 4 eligible cohorts: fresh_cohort, stale_24h, stale_36h, stale_48h
            # Excluded: null_last_calc (no last_calculation), deleted_cohort, static_cohort, high_errors
            mock_total_set.assert_called_once_with(4)

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
            self.assertFalse(static_cohort.is_calculating)  # Static cohorts are now also reset
            self.assertTrue(deleted_cohort.is_calculating)  # Should still be calculating
            self.assertTrue(null_last_calc_cohort.is_calculating)  # Should still be calculating
            self.assertFalse(not_calculating_cohort.is_calculating)  # Should remain not calculating

            # Verify logging - both dynamic and static resets are logged
            warning_calls = mock_logger.warning.call_args_list
            dynamic_reset_call = [c for c in warning_calls if c[0][0] == "reset_stuck_cohorts"]
            self.assertEqual(len(dynamic_reset_call), 1)
            self.assertEqual(
                set(dynamic_reset_call[0][1]["cohort_ids"]),
                {stuck_cohort_1.pk, stuck_cohort_2.pk},
            )

            static_reset_call = [c for c in warning_calls if c[0][0] == "reset_stuck_static_cohorts"]
            self.assertEqual(len(static_reset_call), 1)
            self.assertIn(static_cohort.pk, static_reset_call[0][1]["cohort_ids"])

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
            warning_calls = mock_logger.warning.call_args_list
            dynamic_reset_calls = [c for c in warning_calls if c[0][0] == "reset_stuck_cohorts"]
            self.assertEqual(len(dynamic_reset_calls), 1)
            self.assertEqual(len(dynamic_reset_calls[0][1]["cohort_ids"]), MAX_STUCK_COHORTS_TO_RESET)
            self.assertEqual(dynamic_reset_calls[0][1]["count"], MAX_STUCK_COHORTS_TO_RESET)

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_retriggers_query(
            self, mock_logger: MagicMock, mock_insert_cohort_from_query: MagicMock
        ) -> None:
            now = timezone.now()

            # Create a stuck static cohort with a query, null last_calculation, created > 1 hour ago
            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_with_query",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,
                query={
                    "kind": "HogQLQuery",
                    "query": "SELECT person_id FROM cohort_people WHERE cohort_id = 123",
                },
            )
            # Set created_at to more than 1 hour ago (auto_now_add prevents setting on create)
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            self.assertFalse(stuck_static_cohort.is_calculating)
            self.assertEqual(stuck_static_cohort.errors_calculating, 1)

            # Verify insert_cohort_from_query was re-dispatched
            mock_insert_cohort_from_query.delay.assert_called_with(stuck_static_cohort.pk, self.team.pk)

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_stops_after_max_errors(
            self, mock_logger: MagicMock, mock_insert_cohort_from_query: MagicMock
        ) -> None:
            now = timezone.now()

            # Create a stuck static cohort that has already hit MAX_ERRORS_CALCULATING
            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_max_errors",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=MAX_ERRORS_CALCULATING,
                is_static=True,
                query={
                    "kind": "HogQLQuery",
                    "query": "SELECT person_id FROM cohort_people WHERE cohort_id = 123",
                },
            )
            # Set created_at to more than 1 hour ago
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            # Should NOT be picked up because errors_calculating is at the max
            self.assertTrue(stuck_static_cohort.is_calculating)

            # Verify insert_cohort_from_query was NOT called
            mock_insert_cohort_from_query.delay.assert_not_called()

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_filters")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_retriggers_filters(
            self, mock_logger: MagicMock, mock_insert_cohort_from_filters: MagicMock
        ) -> None:
            now = timezone.now()

            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_with_filters",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [{"key": "email", "type": "person", "value": "match@example.com"}],
                            }
                        ],
                    }
                },
            )
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            self.assertFalse(stuck_static_cohort.is_calculating)
            self.assertEqual(stuck_static_cohort.errors_calculating, 1)
            mock_insert_cohort_from_filters.delay.assert_called_with(stuck_static_cohort.pk, self.team.pk)

        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_query")
        @patch("posthog.tasks.calculate_cohort.insert_cohort_from_filters")
        @patch("posthog.tasks.calculate_cohort.logger")
        def test_reset_stuck_static_cohorts_without_retriggerable_source(
            self,
            mock_logger: MagicMock,
            mock_insert_cohort_from_filters: MagicMock,
            mock_insert_cohort_from_query: MagicMock,
        ) -> None:
            now = timezone.now()

            stuck_static_cohort = Cohort.objects.create(
                team_id=self.team.pk,
                name="stuck_static_without_source",
                last_calculation=None,
                deleted=False,
                is_calculating=True,
                errors_calculating=0,
                is_static=True,
                filters={"properties": {}},
            )
            Cohort.objects.filter(pk=stuck_static_cohort.pk).update(created_at=now - relativedelta(hours=2))

            reset_stuck_cohorts()

            stuck_static_cohort.refresh_from_db()
            self.assertFalse(stuck_static_cohort.is_calculating)
            self.assertEqual(stuck_static_cohort.errors_calculating, 1)
            mock_insert_cohort_from_filters.delay.assert_not_called()
            mock_insert_cohort_from_query.delay.assert_not_called()

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
                        "values": [
                            {
                                "key": "$some_prop_a",
                                "value": "something_a",
                                "type": "person",
                            }
                        ],
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
                        "values": [
                            {
                                "key": "$some_prop_b",
                                "value": "something_b",
                                "type": "person",
                            }
                        ],
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
                    "properties": {
                        "type": "AND",
                        "values": [{"key": "id", "value": cohort_c.id, "type": "cohort"}],
                    }
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

            self.assertEqual(
                set(actual_cohort_order),
                {cohort_a.id, cohort_b.id, cohort_c.id, cohort_d.id},
            )

            # Verify dependency constraints:
            # Both A and B (leaf nodes) must come before C
            a_index = actual_cohort_order.index(cohort_a.id)
            b_index = actual_cohort_order.index(cohort_b.id)
            c_index = actual_cohort_order.index(cohort_c.id)
            d_index = actual_cohort_order.index(cohort_d.id)

            self.assertLess(a_index, c_index, "Cohort A must be processed before C (dependency)")
            self.assertLess(b_index, c_index, "Cohort B must be processed before C (dependency)")
            self.assertLess(c_index, d_index, "Cohort C must be processed before D (dependency)")

            # Verify countdown: first task has no countdown, all subsequent have countdown=2
            # mock_calculate_cohort_ch_si returns mock_task, and .set() is called on it for non-first tasks
            set_calls = mock_task.set.call_args_list
            self.assertEqual(len(set_calls), 3, "3 of 4 tasks should have .set(countdown=2) called")
            for call in set_calls:
                self.assertEqual(call, ((), {"countdown": 2}))

            mock_chain.assert_called_once()
            mock_chain_instance.apply_async.assert_called_once()

        @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.delay")
        def test_increment_version_and_enqueue_single_cohort_has_no_countdown(
            self, mock_calculate_cohort_ch_delay: MagicMock
        ) -> None:
            cohort = Cohort.objects.create(
                team=self.team,
                name="Standalone Cohort",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            }
                        ],
                    }
                },
                is_static=False,
            )

            increment_version_and_enqueue_calculate_cohort(cohort, initiating_user=None)

            mock_calculate_cohort_ch_delay.assert_called_once()
            call_args = mock_calculate_cohort_ch_delay.call_args[0]
            self.assertEqual(
                len(call_args),
                3,
                "Single cohort path should use .delay() with no countdown",
            )

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
                        "values": [
                            {
                                "key": "$some_prop_a",
                                "value": "something_a",
                                "type": "person",
                            }
                        ],
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
                            {
                                "key": "id",
                                "value": MISSING_COHORT_ID,
                                "type": "cohort",
                            },  # non-existent cohort
                            {"key": "id", "value": cohort_a.id, "type": "cohort"},
                            {
                                "key": "$some_prop",
                                "value": "something",
                                "type": "person",
                            },
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
                            {
                                "key": "id",
                                "value": static_cohort_a.id,
                                "type": "cohort",
                            },
                            {
                                "key": "$dynamic_prop",
                                "value": "dynamic_value",
                                "type": "person",
                            },
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
                        "values": [
                            {
                                "key": "$some_prop_a",
                                "value": "something_a",
                                "type": "person",
                            }
                        ],
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
                            {
                                "key": "$some_prop_b",
                                "value": "something_b",
                                "type": "person",
                            },
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
                            {
                                "key": "$some_prop_c",
                                "value": "something_c",
                                "type": "person",
                            },
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
                        {
                            "key": "$some_prop_a",
                            "value": "something_a",
                            "type": "person",
                        },
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


class TestCohortCalculationTasks(APIBaseTest):
    def test_safe_save_cohort_state_handles_errors(self) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_cohort",
            is_static=True,
            count=0,
        )

        with patch.object(cohort, "save", side_effect=Exception("Database error")) as mock_save:
            cohort._safe_save_cohort_state(team_id=self.team.pk, processing_error=None)

        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)
        self.assertEqual(mock_save.call_count, 2)

    @parameterized.expand(
        [
            ("success", None, ["is_calculating", "last_calculation", "errors_calculating", "count"]),
            (
                "error",
                Exception("processing failed"),
                ["is_calculating", "errors_calculating", "last_error_at", "count"],
            ),
        ]
    )
    def test_safe_save_cohort_state_passes_update_fields(
        self, _name: str, processing_error: Exception | None, expected_update_fields: list[str]
    ) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_cohort",
            is_static=True,
            count=0,
        )

        with patch.object(cohort, "save") as mock_save:
            cohort._safe_save_cohort_state(team_id=self.team.pk, processing_error=processing_error)

        mock_save.assert_called_once_with(update_fields=expected_update_fields)

    def test_safe_save_cohort_state_does_not_trigger_downstream_signals(self) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_cohort",
            is_static=True,
            count=0,
        )

        with (
            patch("posthog.models.cohort.dependencies._on_cohort_changed") as mock_dep_cache,
            patch("posthog.tasks.feature_flags.update_team_flags_cache") as mock_flags_cache,
            patch("posthog.tasks.hog_functions.refresh_affected_hog_functions") as mock_hog_refresh,
        ):
            cohort._safe_save_cohort_state(team_id=self.team.pk, processing_error=None)

        mock_dep_cache.assert_not_called()
        mock_flags_cache.delay.assert_not_called()
        mock_hog_refresh.delay.assert_not_called()

    def test_insert_cohort_from_query_count_updated_on_exception(self) -> None:
        from posthog.tasks.calculate_cohort import insert_cohort_from_query

        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_query_cohort",
            is_static=True,
            count=0,
            query={"kind": "HogQLQuery", "query": "SELECT person_id FROM persons LIMIT 10"},
        )

        with (
            patch("posthog.models.cohort.util.insert_cohort_query_actors_into_ch") as mock_insert_ch,
            patch("posthog.models.cohort.util.insert_cohort_people_into_pg") as mock_insert_pg,
        ):
            mock_insert_ch.side_effect = Exception("Simulated query processing error")
            mock_insert_pg.side_effect = Exception("Simulated pg insert error")

            insert_cohort_from_query(cohort.id, self.team.pk)

            cohort.refresh_from_db()
            self.assertEqual(
                cohort.count, 0, "Count should be updated using PostgreSQL even when query processing fails"
            )
            self.assertFalse(cohort.is_calculating, "Cohort should not be in calculating state")
            self.assertGreater(cohort.errors_calculating, 0, "Should have recorded the processing error")

    def test_insert_cohort_from_filters_count_updated_on_exception(self) -> None:
        cohort = Cohort.objects.create(
            team_id=self.team.pk,
            name="test_filters_cohort",
            is_static=True,
            count=0,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "email", "type": "person", "value": "match@example.com"}],
                        }
                    ],
                }
            },
        )

        with (
            patch("posthog.models.cohort.util.insert_cohort_filter_actors_into_ch") as mock_insert_ch,
            patch("posthog.models.cohort.util.insert_cohort_people_into_pg") as mock_insert_pg,
        ):
            mock_insert_ch.side_effect = Exception("Simulated filter processing error")
            mock_insert_pg.side_effect = Exception("Simulated pg insert error")

            insert_cohort_from_filters(cohort.id, self.team.pk)

            cohort.refresh_from_db()
            self.assertEqual(cohort.count, 0, "Count should remain available even when filter processing fails")
            self.assertFalse(cohort.is_calculating, "Cohort should not be in calculating state")
            self.assertGreater(cohort.errors_calculating, 0, "Should have recorded the processing error")

    @patch("posthog.tasks.calculate_cohort.chain")
    @patch("posthog.tasks.calculate_cohort.calculate_cohort_ch.si")
    def test_increment_version_and_enqueue_calculate_cohort_with_referencing_cohorts(
        self, mock_calculate_cohort_ch_si: MagicMock, mock_chain: MagicMock
    ) -> None:
        cohort_a = Cohort.objects.create(
            team=self.team,
            name="Cohort A",
            filters={
                "properties": {"type": "AND", "values": [{"key": "$browser", "value": "Chrome", "type": "person"}]}
            },
            is_static=False,
        )

        cohort_b = Cohort.objects.create(
            team=self.team,
            name="Cohort B (references A)",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort_a.id, "type": "cohort"},
                        {"key": "$os", "value": "Windows", "type": "person"},
                    ],
                }
            },
            is_static=False,
        )

        cohort_c = Cohort.objects.create(
            team=self.team,
            name="Cohort C (references B)",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "value": cohort_b.id, "type": "cohort"},
                        {"key": "$country", "value": "US", "type": "person"},
                    ],
                }
            },
            is_static=False,
        )

        mock_chain_instance = MagicMock()
        mock_chain.return_value = mock_chain_instance
        mock_task = MagicMock()
        mock_calculate_cohort_ch_si.return_value = mock_task

        increment_version_and_enqueue_calculate_cohort(cohort_a, initiating_user=None)

        self.assertEqual(mock_calculate_cohort_ch_si.call_count, 3)

        actual_calls = mock_calculate_cohort_ch_si.call_args_list
        actual_cohort_ids = {call[0][0] for call in actual_calls}
        expected_cohort_ids = {cohort_a.id, cohort_b.id, cohort_c.id}
        self.assertEqual(actual_cohort_ids, expected_cohort_ids)

        mock_chain.assert_called_once()
        mock_chain_instance.apply_async.assert_called_once()
