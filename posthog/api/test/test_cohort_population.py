from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, flush_persons_and_events
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from rest_framework import status

from posthog.models.utils import uuid7
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
from products.cohorts.backend.population.test.storage_fake import fake_population_storage

DURABLE = {"COHORT_POPULATION_DURABLE_ADMISSION_TEAM_ALLOWLIST": "all"}


@override_settings(**DURABLE)
class TestCohortPopulationApi(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.storage = self.enterContext(fake_population_storage())
        self.cohort = Cohort.objects.create(team=self.team, name="uploaded people", is_static=True)

    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.pk}/cohorts/{self.cohort.pk}/{suffix}"

    def _operation(self, **overrides) -> CohortPopulationOperation:
        operation = lifecycle.admit(
            operation_id=uuid7(),
            cohort=self.cohort,
            team_id=self.team.pk,
            source=CohortPopulationSource.LIST,
            input_manifest={
                "schema": 1,
                "prefix": "cohort_population/team-x/op",
                "chunks": 1,
                "total": 3,
                "id_type": "person_id",
            },
        )
        self.storage.objects["cohort_population/team-x/op/chunk-000000.json"] = "[]"
        if overrides:
            CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(**overrides)
            operation.refresh_from_db()
        return operation

    def test_a_static_cohort_reports_its_current_run(self) -> None:
        operation = self._operation()

        population = self.client.get(self._url()).json()["population"]

        assert population["id"] == str(operation.pk)
        assert population["status"] == CohortPopulationStatus.PENDING
        assert population["phase"] == CohortPopulationPhase.WRITING_MEMBERSHIP
        assert population["source"] == CohortPopulationSource.LIST
        assert population["progress"] == {
            "identifiers_total": 3,
            "identifiers_written": 0,
            "matched": 0,
            "unmatched": 0,
        }
        assert population["error_message"] is None
        assert population["available_actions"] == ["abandon"]

    def test_a_cohort_with_no_run_reports_no_population(self) -> None:
        assert self.client.get(self._url()).json()["population"] is None

    def test_a_failed_run_that_can_resume_offers_retry_and_one_that_cannot_offers_reupload(self) -> None:
        operation = self._operation(
            status=CohortPopulationStatus.FAILED, error_code=CohortErrorCode.CAPACITY, finished_at=timezone.now()
        )

        population = self.client.get(self._url()).json()["population"]
        assert population["available_actions"] == ["retry", "abandon"]
        assert population["input_available"] is True
        assert population["error_message"]

        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(
            input_deleted_at=timezone.now(), error_code=CohortErrorCode.INPUT_UNAVAILABLE
        )

        population = self.client.get(self._url()).json()["population"]
        assert population["available_actions"] == ["reupload", "abandon"]
        assert population["input_available"] is False

    def test_the_list_endpoint_leaves_population_out(self) -> None:
        self._operation()

        rows = self.client.get(f"/api/projects/{self.team.pk}/cohorts/").json()["results"]

        assert [row["population"] for row in rows] == [None]

    def test_adding_people_while_a_run_is_unresolved_is_refused(self) -> None:
        operation = self._operation()
        person = create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()

        response = self.client.patch(self._url("add_persons_to_static_cohort"), {"person_ids": [str(person.uuid)]})

        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["code"] == "population_in_progress"
        assert body["extra"]["population"]["id"] == str(operation.pk)

    def test_removing_a_person_while_a_run_is_unresolved_is_refused(self) -> None:
        self._operation()
        person = create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()

        response = self.client.patch(self._url("remove_person_from_static_cohort"), {"person_id": str(person.uuid)})

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_uploading_another_csv_while_a_run_is_unresolved_is_refused(self) -> None:
        self._operation()
        csv = SimpleUploadedFile("people.csv", b"someone\n", content_type="application/csv")

        response = self.client.patch(self._url(), {"csv": csv}, format="multipart")

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_a_metadata_edit_is_still_allowed_while_a_run_is_unresolved(self) -> None:
        self._operation()

        payload = self.client.get(self._url()).json()
        payload["name"] = "renamed while populating"
        response = self.client.patch(self._url(), payload)

        assert response.status_code == status.HTTP_200_OK
        self.cohort.refresh_from_db()
        assert self.cohort.name == "renamed while populating"

    def test_membership_edits_are_allowed_again_once_the_run_resolves(self) -> None:
        self._operation(status=CohortPopulationStatus.COMPLETED, finished_at=timezone.now())
        person = create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()

        response = self.client.patch(self._url("add_persons_to_static_cohort"), {"person_ids": [str(person.uuid)]})

        assert response.status_code == status.HTTP_200_OK

    def test_adding_people_from_another_team_does_not_report_success(self) -> None:
        other_team = self.organization.teams.create(name="other")
        person = create_person(team=other_team, distinct_ids=["other-team-person"])
        flush_persons_and_events()
        response = self.client.patch(self._url("add_persons_to_static_cohort"), {"person_ids": [str(person.uuid)]})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert count_cohort_members(team_id=self.team.pk, cohort_id=self.cohort.pk, consistency="strong") == 0

    def test_adding_people_answers_success_only_after_both_stores_hold_them(self) -> None:
        person = create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()

        response = self.client.patch(self._url("add_persons_to_static_cohort"), {"person_ids": [str(person.uuid)]})

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"success": True}
        assert count_cohort_members(team_id=self.team.pk, cohort_id=self.cohort.pk, consistency="strong") == 1

    def test_a_dependency_failure_while_adding_people_answers_with_the_recoverable_run(self) -> None:
        person = create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()

        with patch.object(runner, "_resolve_and_insert", side_effect=ConnectionError("personhog went away")):
            response = self.client.patch(self._url("add_persons_to_static_cohort"), {"person_ids": [str(person.uuid)]})

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        body = response.json()
        assert body["code"] == "population_failed"
        assert body["extra"]["population"]["status"] == CohortPopulationStatus.RETRY_SCHEDULED
        assert lifecycle.unresolved_operation_for(self.cohort.pk) is not None

    def test_retrying_a_failed_run_resumes_it_and_reports_the_new_state(self) -> None:
        operation = self._operation(
            status=CohortPopulationStatus.FAILED,
            error_code=CohortErrorCode.CAPACITY,
            attempts=6,
            finished_at=timezone.now(),
            progress={"chunk_index": 1, "matched": 900, "unmatched": 100},
        )

        with patch("posthog.api.cohort.dispatch_operation") as dispatched:
            response = self.client.post(self._url("retry_population"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == CohortPopulationStatus.PENDING
        assert response.json()["attempts"] == 0
        assert response.json()["progress"]["identifiers_written"] == 1000
        dispatched.assert_called_once()
        self.cohort.refresh_from_db()
        assert self.cohort.is_calculating is True
        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.PENDING

    def test_retrying_a_run_whose_input_is_gone_is_refused_rather_than_promising_recovery(self) -> None:
        self._operation(
            status=CohortPopulationStatus.FAILED,
            error_code=CohortErrorCode.INPUT_UNAVAILABLE,
            finished_at=timezone.now(),
        )
        self.storage.objects.clear()

        response = self.client.post(self._url("retry_population"))

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["code"] == "population_not_retryable"

    def test_retrying_a_run_that_has_not_failed_is_refused(self) -> None:
        self._operation()

        response = self.client.post(self._url("retry_population"))

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_retrying_with_no_run_at_all_is_a_404(self) -> None:
        assert self.client.post(self._url("retry_population")).status_code == status.HTTP_404_NOT_FOUND

    def test_abandoning_asks_the_run_to_stop_rather_than_cutting_it_off(self) -> None:
        operation = self._operation()

        with patch("posthog.api.cohort.dispatch_operation") as dispatched:
            response = self.client.post(self._url("abandon_population"))

        assert response.status_code == status.HTTP_200_OK
        dispatched.assert_called_once()
        operation.refresh_from_db()
        assert operation.abandon_requested_at is not None
        assert operation.status in (CohortPopulationStatus.PENDING, CohortPopulationStatus.RUNNING)

    def test_abandoning_when_nothing_is_running_is_a_404(self) -> None:
        self._operation(status=CohortPopulationStatus.COMPLETED, finished_at=timezone.now())

        assert self.client.post(self._url("abandon_population")).status_code == status.HTTP_404_NOT_FOUND

    def test_another_team_cannot_retry_or_abandon_this_cohorts_run(self) -> None:
        self._operation(status=CohortPopulationStatus.FAILED, finished_at=timezone.now())
        other_team = self.organization.teams.create(name="other")

        for action in ("retry_population", "abandon_population"):
            response = self.client.post(f"/api/projects/{other_team.pk}/cohorts/{self.cohort.pk}/{action}")
            assert response.status_code == status.HTTP_404_NOT_FOUND, action


@override_settings(**DURABLE)
class TestCohortPopulationAdmission(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.storage = self.enterContext(fake_population_storage())

    def test_a_csv_upload_persists_its_identifiers_before_the_work_is_accepted(self) -> None:
        create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()
        csv = SimpleUploadedFile("people.csv", b"someone\nnobody\n", content_type="application/csv")

        with patch("products.cohorts.backend.population.admission.dispatch_operation"):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/cohorts/",
                {"name": "from csv", "csv": csv, "is_static": True},
                format="multipart",
            )

        assert response.status_code == status.HTTP_201_CREATED
        operation = lifecycle.unresolved_operation_for(response.json()["id"])
        assert operation is not None
        assert operation.input_manifest is not None
        assert operation.input_manifest["total"] == 2
        assert self.storage.objects != {}

    def test_the_upload_survives_a_worker_that_never_ran_and_finishes_on_the_next_dispatch(self) -> None:
        create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()
        csv = SimpleUploadedFile("people.csv", b"someone\n", content_type="application/csv")

        with patch("products.cohorts.backend.population.admission.dispatch_operation"):
            cohort_id = self.client.post(
                f"/api/projects/{self.team.pk}/cohorts/",
                {"name": "from csv", "csv": csv, "is_static": True},
                format="multipart",
            ).json()["id"]

        operation = lifecycle.unresolved_operation_for(cohort_id)
        assert operation is not None
        CohortPopulationOperation.objects.unscoped().filter(pk=operation.pk).update(
            dispatched_at=timezone.now() - timedelta(hours=1)
        )

        from products.cohorts.backend.population.dispatch import dispatch_ready_operations

        assert dispatch_ready_operations().missed_dispatch == 1

        operation.refresh_from_db()
        assert operation.status == CohortPopulationStatus.COMPLETED
        assert count_cohort_members(team_id=self.team.pk, cohort_id=cohort_id, consistency="strong") == 1

    def test_creating_with_person_ids_answers_with_the_cohort_when_the_write_does_not_finish(self) -> None:
        person = create_person(team=self.team, distinct_ids=["someone"])
        flush_persons_and_events()

        with patch.object(runner, "_resolve_and_insert", side_effect=ConnectionError("personhog went away")):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/cohorts/",
                {"name": "from people", "is_static": True, "_create_static_person_ids": [str(person.uuid)]},
                format="multipart",
            )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["population"]["status"] == CohortPopulationStatus.RETRY_SCHEDULED
        assert lifecycle.unresolved_operation_for(body["id"]) is not None
