from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, flush_persons_and_events
from unittest.mock import patch

from django.db import OperationalError
from django.db.models.query import QuerySet
from django.test import override_settings

import requests
from parameterized import parameterized
from requests.exceptions import HTTPError

from posthog.api.services.flags_service import FlagVersionConflictError
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.population import (
    CohortPopulationOperation,
    CohortPopulationPhase,
    CohortPopulationSource,
    CohortPopulationStatus,
)
from products.cohorts.backend.models.util import CohortErrorCode, count_cohort_members
from products.cohorts.backend.population import (
    operation as lifecycle,
    runner,
)
from products.cohorts.backend.population.admission import (
    admit_feature_flag_population,
    admit_list_population,
    admit_query_or_filters_population,
)
from products.cohorts.backend.population.flag_pages import COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER
from products.cohorts.backend.population.progress import PopulationProgress
from products.cohorts.backend.population.test.storage_fake import fake_population_storage
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestCohortPopulationRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cohort = Cohort.objects.create(team=self.team, name="uploaded people", is_static=True)
        self.storage = self.enterContext(fake_population_storage())

    def _people(self, count: int, prefix: str = "person") -> list[str]:
        distinct_ids = []
        for index in range(count):
            distinct_id = f"{prefix}-{index}"
            create_person(team=self.team, distinct_ids=[distinct_id])
            distinct_ids.append(distinct_id)
        flush_persons_and_events()
        return distinct_ids

    def _members(self) -> int:
        return count_cohort_members(team_id=self.team.pk, cohort_id=self.cohort.pk, consistency="strong")

    def test_replaced_worker_stops_after_its_uncheckpointed_batch(self) -> None:
        identifiers = self._people(4)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=identifiers, id_type="distinct_id", dispatch=False
        )
        self._rechunk(operation, identifiers, chunk_size=2)
        insert = runner._resolve_and_insert

        def replace_after_write(*args, **kwargs):
            result = insert(*args, **kwargs)
            CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(claim_token=uuid4())
            return result

        with patch.object(runner, "_resolve_and_insert", side_effect=replace_after_write) as write:
            runner.run_operation(operation.pk, max_work_units=50)
        assert write.call_count == 1
        operation.refresh_from_db()
        assert PopulationProgress.from_json(operation.progress).chunk_index == 0
        assert operation.status == CohortPopulationStatus.RUNNING
        assert self._members() == 2

    def test_abandonment_repairs_an_interrupted_batch_but_does_not_import_the_remainder(self) -> None:
        identifiers = self._people(4)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=identifiers, id_type="distinct_id", dispatch=False
        )
        self._rechunk(operation, identifiers, chunk_size=2)
        with patch(
            "products.cohorts.backend.models.util.insert_cohort_members", side_effect=ConnectionError("unavailable")
        ):
            runner.run_operation(operation.pk, max_work_units=50)
        assert self._members() == 0
        lifecycle.request_abandon(operation)
        runner.run_operation(operation.pk, max_work_units=50)
        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.ABANDONED
        assert self._members() == self.cohort.count == 2
        assert self.cohort.last_import_total_count is None
        assert self.cohort.errors_calculating > 0

    def test_final_bookkeeping_is_atomic_and_retries_without_replaying_membership(self) -> None:
        identifiers = self._people(2)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=identifiers, id_type="distinct_id", dispatch=False
        )
        update = QuerySet.update

        def fail_cohort_finalization(queryset, **kwargs):
            if queryset.model is Cohort and "last_calculation" in kwargs:
                raise OperationalError("bookkeeping unavailable")
            return update(queryset, **kwargs)

        with patch.object(QuerySet, "update", fail_cohort_finalization):
            runner.run_operation(operation.pk, max_work_units=50)
        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.RETRY_SCHEDULED
        assert operation.phase == CohortPopulationPhase.FINALIZING
        assert self.cohort.is_calculating is True
        assert self.cohort.last_import_total_count is None
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(next_attempt_at=None)
        with patch.object(runner, "_resolve_and_insert", side_effect=AssertionError("membership must not replay")):
            runner.run_operation(operation.pk, max_work_units=50)
        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert self.cohort.count == 2
        assert self.cohort.last_import_total_count == 2

    def test_a_multi_chunk_upload_writes_every_chunk_and_finishes_the_cohort(self) -> None:
        distinct_ids = self._people(5)
        operation = admit_list_population(
            cohort=self.cohort,
            team_id=self.team.pk,
            identifiers=distinct_ids,
            id_type="distinct_id",
            dispatch=False,
        )
        self._rechunk(operation, distinct_ids, chunk_size=3)

        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert operation.phase == CohortPopulationPhase.DONE
        assert self._members() == 5
        assert self.cohort.is_calculating is False
        assert self.cohort.count == 5
        assert self.cohort.last_import_total_count == 5
        assert self.cohort.last_import_unmatched_count == 0

    def test_a_failure_between_chunks_resumes_at_the_chunk_it_stopped_on(self) -> None:
        distinct_ids = self._people(6)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=distinct_ids, id_type="distinct_id", dispatch=False
        )
        self._rechunk(operation, distinct_ids, chunk_size=2)

        real_resolve = runner._resolve_and_insert
        calls: list[int] = []

        def fail_on_the_second_chunk(cohort, chunk, *, id_type, team_id):
            calls.append(1)
            if len(calls) == 2:
                raise ConnectionError("personhog went away")
            return real_resolve(cohort, chunk, id_type=id_type, team_id=team_id)

        with patch.object(runner, "_resolve_and_insert", side_effect=fail_on_the_second_chunk):
            runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.RETRY_SCHEDULED
        assert PopulationProgress.from_json(operation.progress).chunk_index == 1
        assert self._members() == 2

        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(next_attempt_at=None)
        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert self._members() == 6
        assert self.cohort.last_import_total_count == 6

    def test_replaying_a_chunk_after_a_crash_between_the_two_stores_adds_nobody_twice(self) -> None:
        distinct_ids = self._people(4)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=distinct_ids, id_type="distinct_id", dispatch=False
        )

        with patch.object(lifecycle, "checkpoint", return_value=False):
            runner.run_operation(operation.pk, max_work_units=1)
        assert self._members() == 4

        CohortPopulationOperation.objects.unscoped().filter(
            pk=operation.pk, status=CohortPopulationStatus.RUNNING
        ).update(status=CohortPopulationStatus.PENDING, claim_token=None, lease_expires_at=None)
        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert self._members() == 4

    def test_unmatched_identifiers_still_advance_the_run_and_are_reported(self) -> None:
        matched = self._people(2)
        operation = admit_list_population(
            cohort=self.cohort,
            team_id=self.team.pk,
            identifiers=[*matched, "nobody-1", "nobody-2", "nobody-3"],
            id_type="distinct_id",
            dispatch=False,
        )

        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert self.cohort.last_import_total_count == 5
        assert self.cohort.last_import_unmatched_count == 3
        assert self._members() == 2

    def test_an_empty_upload_completes_rather_than_leaving_the_cohort_calculating(self) -> None:
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=[], id_type="person_id", dispatch=False
        )

        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert self.cohort.is_calculating is False
        assert self.cohort.count == 0

    def test_input_that_left_storage_fails_the_run_permanently_instead_of_retrying_forever(self) -> None:
        distinct_ids = self._people(2)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=distinct_ids, id_type="distinct_id", dispatch=False
        )
        self.storage.objects.clear()

        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.FAILED
        assert operation.error_code == CohortErrorCode.INPUT_UNAVAILABLE
        assert operation.attempts == 1
        assert self.cohort.is_calculating is False
        assert self.cohort.errors_calculating == 1

    def test_a_transient_failure_leaves_the_cohort_calculating_while_attempts_remain(self) -> None:
        distinct_ids = self._people(2)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=distinct_ids, id_type="distinct_id", dispatch=False
        )

        with patch.object(runner, "_resolve_and_insert", side_effect=ConnectionError("personhog went away")):
            runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.RETRY_SCHEDULED
        assert self.cohort.is_calculating is True
        assert self.cohort.errors_calculating == 0

    def test_a_finalization_failure_retries_finalization_without_replaying_membership(self) -> None:
        distinct_ids = self._people(3)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=distinct_ids, id_type="distinct_id", dispatch=False
        )

        with patch.object(runner, "count_cohort_members", side_effect=ConnectionError("count failed")):
            runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        assert operation.phase == CohortPopulationPhase.FINALIZING
        assert operation.status == CohortPopulationStatus.RETRY_SCHEDULED
        assert self._members() == 3

        resolve_calls: list[int] = []
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(next_attempt_at=None)
        with patch.object(runner, "_resolve_and_insert", side_effect=lambda *a, **k: resolve_calls.append(1)):
            runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert resolve_calls == []

    def test_abandonment_keeps_what_was_written_and_records_an_incomplete_outcome(self) -> None:
        distinct_ids = self._people(4)
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=distinct_ids, id_type="distinct_id", dispatch=False
        )
        self._rechunk(operation, distinct_ids, chunk_size=2)
        runner.run_operation(operation.pk, max_work_units=1)

        lifecycle.request_abandon(operation)
        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.ABANDONED
        assert self._members() == 2
        assert self.cohort.count == 2
        assert self.cohort.is_calculating is False
        assert self.cohort.last_import_total_count is None

    def test_a_synchronization_failure_does_not_reevaluate_an_already_materialized_source(self) -> None:
        source_cohort = Cohort.objects.create(
            team=self.team, name="from query", is_static=True, query={"kind": "ActorsQuery"}
        )
        operation = admit_query_or_filters_population(
            cohort=source_cohort, team_id=self.team.pk, source=CohortPopulationSource.QUERY, dispatch=False
        )

        with patch("products.cohorts.backend.models.util.insert_cohort_query_actors_into_ch") as materialize:
            with patch.object(runner, "_synchronize_next_page", side_effect=ConnectionError("personhog went away")):
                runner.run_operation(operation.pk, max_work_units=50)

            operation.refresh_from_db()
            assert materialize.call_count == 1
            assert PopulationProgress.from_json(operation.progress).source_materialized is True
            assert operation.phase == CohortPopulationPhase.SYNCHRONIZING
            assert operation.status == CohortPopulationStatus.RETRY_SCHEDULED

            CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(next_attempt_at=None)
            runner.run_operation(operation.pk, max_work_units=50)

            assert materialize.call_count == 1

        operation.refresh_from_db()
        source_cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert source_cohort.is_calculating is False

    def _rechunk(self, operation: CohortPopulationOperation, identifiers: list[str], *, chunk_size: int) -> None:
        """Rewrite the operation's input at a smaller chunk size, to exercise the multi-chunk path."""
        from products.cohorts.backend.population.input_store import write_input

        assert operation.input_manifest is not None
        manifest = write_input(
            team_id=operation.team_id,
            operation_id=operation.pk,
            identifiers=identifiers,
            id_type=operation.input_manifest["id_type"],
            chunk_size=chunk_size,
        )
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(input_manifest=manifest)
        operation.refresh_from_db()


class TestCohortPopulationRunnerConcurrency(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cohort = Cohort.objects.create(team=self.team, name="uploaded people", is_static=True)
        self.storage = self.enterContext(fake_population_storage())

    @override_settings(COHORT_POPULATION_LEASE_SECONDS=3600)
    def test_a_duplicate_delivery_does_no_work_while_another_attempt_holds_the_lease(self) -> None:
        create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()
        operation = admit_list_population(
            cohort=self.cohort, team_id=self.team.pk, identifiers=["someone"], id_type="distinct_id", dispatch=False
        )
        held = lifecycle.claim(operation.pk, worker="worker-a")
        assert held is not None

        with patch.object(runner, "_resolve_and_insert") as resolve:
            runner.run_operation(operation.pk, worker="worker-b")

        resolve.assert_not_called()
        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.RUNNING


class TestCohortPopulationRunnerFeatureFlagSource(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.cohort = Cohort.objects.create(team=self.team, name="from flag", is_static=True)
        self.storage = self.enterContext(fake_population_storage())
        self.flag = FeatureFlag.objects.create(team=self.team, key="beta", created_by=self.user, active=True)

    def _admit(self):
        return admit_feature_flag_population(cohort=self.cohort, team_id=self.team.pk, flag_key="beta", dispatch=False)

    def test_the_cohort_stays_calculating_until_the_last_page_is_written(self) -> None:
        people = [create_person(team=self.team, distinct_ids=[f"flagged-{index}"]) for index in range(4)]
        flush_persons_and_events()
        pages = [
            {"matched_person_uuids": [str(people[0].uuid), str(people[1].uuid)], "next_cursor": 2, "errors_count": 0},
            {
                "matched_person_uuids": [str(people[2].uuid), str(people[3].uuid)],
                "next_cursor": None,
                "errors_count": 0,
            },
        ]
        operation = self._admit()

        with patch.object(runner, "batch_evaluate_flag_page_with_retries", side_effect=pages):
            runner.run_operation(operation.pk, max_work_units=1)
            self.cohort.refresh_from_db()
            assert self.cohort.is_calculating is True

            runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert Cohort.objects.get(pk=self.cohort.pk).is_calculating is False
        assert count_cohort_members(team_id=self.team.pk, cohort_id=self.cohort.pk, consistency="strong") == 4

    def test_every_fetched_page_is_persisted_before_membership_is_written(self) -> None:
        person = create_person(team=self.team, distinct_ids=["flagged"])
        flush_persons_and_events()
        operation = self._admit()

        with patch.object(
            runner,
            "batch_evaluate_flag_page_with_retries",
            return_value={"matched_person_uuids": [str(person.uuid)], "next_cursor": None, "errors_count": 0},
        ):
            runner.run_operation(operation.pk, max_work_units=2)

        operation.refresh_from_db()
        assert operation.input_manifest is not None
        assert operation.input_manifest["chunks"] == 1
        assert operation.phase == CohortPopulationPhase.WRITING_MEMBERSHIP
        assert self.storage.objects != {}

    def test_evaluation_errors_reported_by_a_page_are_counted_rather_than_dropped(self) -> None:
        person = create_person(team=self.team, distinct_ids=["flagged"])
        flush_persons_and_events()
        operation = self._admit()
        errors_before = COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER._value.get()

        with patch.object(
            runner,
            "batch_evaluate_flag_page_with_retries",
            return_value={"matched_person_uuids": [str(person.uuid)], "next_cursor": None, "errors_count": 3},
        ):
            runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert COHORT_FLAG_GENERATION_EVAL_ERRORS_COUNTER._value.get() == errors_before + 3

    def test_a_flag_definition_that_changes_mid_run_fails_the_run_rather_than_mixing_two(self) -> None:
        operation = self._admit()

        with patch.object(
            runner, "batch_evaluate_flag_page_with_retries", side_effect=FlagVersionConflictError("flag changed")
        ):
            runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.FAILED
        assert operation.error_code == CohortErrorCode.FLAG_CHANGED
        assert operation.attempts == 1
        assert self.cohort.is_calculating is False

    def test_a_flag_that_cannot_be_evaluated_finishes_as_an_empty_run(self) -> None:
        self.flag.active = False
        self.flag.save()
        operation = self._admit()

        runner.run_operation(operation.pk, max_work_units=50)

        operation.refresh_from_db()
        self.cohort.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert self.cohort.is_calculating is False
        assert self.cohort.count == 0


def _http_error(status_code: int) -> HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return HTTPError(response=response)


@parameterized.expand(
    [
        ("rejected_request", _http_error(400), False),
        ("missing_flag", _http_error(404), False),
        ("throttled", _http_error(429), True),
        ("service_error", _http_error(503), True),
    ]
)
def test_only_transient_flag_service_responses_are_retried(_name: str, error: Exception, retryable: bool) -> None:
    assert runner._is_retryable(error) is retryable
