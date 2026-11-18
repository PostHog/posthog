"""Tests that person API endpoints produce identical results via personhog.

Covers retrieve, update, split, delete_property, batch_by_distinct_ids, and
person deletion — extracted from test_person.py.
"""

from posthog.test.base import APIBaseTest
from unittest import mock

from django.core.cache import cache
from django.core.signing import TimestampSigner
from django.test import override_settings

from loginas import settings as loginas_settings
from parameterized import parameterized
from rest_framework import status

from posthog.api.person import PersonsDeleteBurstThrottle, PersonsDeleteTeamBurstThrottle
from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.instance_setting import override_instance_config
from posthog.models.person.util import get_person_by_uuid
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_secret, hash_key_value
from posthog.personhog_client.test_helpers import PersonhogTestMixin

from products.cohorts.backend.models.cohort import Cohort

UUID_NONEXISTENT = "550e8400-e29b-41d4-a716-446655440000"


class TestRetrievePerson(PersonhogTestMixin, APIBaseTest):
    def test_retrieve_by_uuid(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1", "did-2"],
            properties={"email": "test@example.com"},
        )

        resp = self.client.get(f"/api/person/{person.uuid}/")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["uuid"] == str(person.uuid)
        assert data["properties"]["email"] == "test@example.com"
        assert set(data["distinct_ids"]) == {"did-1", "did-2"}
        self._assert_personhog_called("get_person_by_uuid")

    def test_retrieve_by_pk(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
            properties={"name": "Test User"},
        )

        resp = self.client.get(f"/api/person/{person.pk}/")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["uuid"] == str(person.uuid)
        assert data["properties"]["name"] == "Test User"
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")

    def test_retrieve_nonexistent_returns_404(self):
        resp = self.client.get(f"/api/person/{UUID_NONEXISTENT}/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_retrieve_invalid_id_returns_validation_error(self):
        resp = self.client.get("/api/person/not-a-valid-id/")

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not look like a personID" in resp.json().get("detail", "")

    def test_retrieve_cross_team_isolation(self):
        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_person = self._seed_person(team=other_team, distinct_ids=["other-did"])

        resp = self.client.get(f"/api/person/{other_person.uuid}/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestUpdatePerson(PersonhogTestMixin, APIBaseTest):
    @mock.patch("posthog.api.person.capture_internal")
    def test_update_properties_by_uuid(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
            properties={"existing": "value"},
        )

        resp = self.client.patch(
            f"/api/person/{person.uuid}/",
            {"properties": {"new_key": "new_value"}},
            format="json",
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        mock_capture.assert_called_once()
        call_kwargs = mock_capture.call_args[1]
        assert call_kwargs["distinct_id"] == "did-1"
        assert call_kwargs["properties"] == {"$set": {"new_key": "new_value"}}
        self._assert_personhog_called("get_person_by_uuid")

    @mock.patch("posthog.api.person.capture_internal")
    def test_update_properties_by_pk(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
            properties={},
        )

        resp = self.client.patch(
            f"/api/person/{person.pk}/",
            {"properties": {"key": "val"}},
            format="json",
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")


class TestSplitPerson(PersonhogTestMixin, APIBaseTest):
    @mock.patch("posthog.api.person.split_person")
    def test_split_by_uuid(self, mock_split):
        mock_split.delay = mock.MagicMock()
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1", "did-2", "did-3"],
        )

        resp = self.client.post(f"/api/person/{person.uuid}/split/")

        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json() == {"success": True}
        mock_split.delay.assert_called_once_with(
            person.pk,
            self.team.pk,
            None,
            None,
            distinct_ids_to_split=None,
        )
        self._assert_personhog_called("get_person_by_uuid")

    @mock.patch("posthog.api.person.split_person")
    def test_split_nonexistent_returns_404(self, mock_split):
        resp = self.client.post(f"/api/person/{UUID_NONEXISTENT}/split/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        mock_split.delay.assert_not_called()


class TestCohortsByPerson(PersonhogTestMixin, APIBaseTest):
    def test_cohorts_by_uuid(self):
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did-1"],
        )
        cohort = Cohort.objects.create(team=self.team, name="Test Cohort")

        with mock.patch(
            "posthog.api.person.get_all_cohort_ids_by_person_uuid",
            return_value=[cohort.pk],
        ):
            resp = self.client.get(f"/api/person/cohorts/?person_id={person.uuid}")

        assert resp.status_code == status.HTTP_200_OK
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Test Cohort"
        self._assert_personhog_called("get_person_by_uuid")

    def test_cohorts_nonexistent_person_returns_404(self):
        with mock.patch(
            "posthog.api.person.get_all_cohort_ids_by_person_uuid",
            return_value=[],
        ):
            resp = self.client.get(f"/api/person/cohorts/?person_id={UUID_NONEXISTENT}")

        assert resp.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteProperty(PersonhogTestMixin, APIBaseTest):
    @mock.patch("posthog.api.person.capture_internal")
    def test_uuid_lookup(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did1", "did2"],
            properties={"foo": "bar"},
        )

        resp = self.client.post(
            f"/api/person/{person.uuid}/delete_property",
            {"$unset": "foo"},
        )

        assert resp.status_code == 201
        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$delete_person_property",
            event_source="person_viewset",
            distinct_id="did1",
            timestamp=mock.ANY,
            properties={"$unset": ["foo"]},
            process_person_profile=True,
        )
        self._assert_personhog_called("get_person_by_uuid")
        self._assert_personhog_called("get_distinct_ids_for_person")

    @mock.patch("posthog.api.person.capture_internal")
    def test_integer_pk_lookup(self, mock_capture):
        mock_capture.return_value = mock.MagicMock(status_code=200)
        person = self._seed_person(
            team=self.team,
            distinct_ids=["did1"],
            properties={"foo": "bar"},
        )

        resp = self.client.post(
            f"/api/person/{person.pk}/delete_property",
            {"$unset": "foo"},
        )

        assert resp.status_code == 201
        self._assert_personhog_not_called("get_person_by_uuid")
        self._assert_personhog_called("get_person")

    def test_uuid_not_found_returns_error(self):
        resp = self.client.post(
            f"/api/person/{UUID_NONEXISTENT}/delete_property",
            {"$unset": "foo"},
        )

        assert resp.status_code != 201


class TestBatchByDistinctIds(PersonhogTestMixin, APIBaseTest):
    def test_happy_path(self):
        self._seed_person(team=self.team, distinct_ids=["user_1"], properties={"email": "user1@example.com"})
        self._seed_person(team=self.team, distinct_ids=["user_2"], properties={"email": "user2@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["user_1", "user_2"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "user_1" in results
        assert "user_2" in results
        assert results["user_1"]["properties"]["email"] == "user1@example.com"
        assert results["user_2"]["properties"]["email"] == "user2@example.com"
        self._assert_personhog_called("get_persons_by_distinct_ids_in_team")

    def test_missing_ids(self):
        self._seed_person(team=self.team, distinct_ids=["existing_user"], properties={"email": "exists@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["existing_user", "nonexistent_1", "nonexistent_2"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "existing_user" in results
        assert "nonexistent_1" not in results
        assert "nonexistent_2" not in results

    def test_same_person_multiple_ids(self):
        self._seed_person(team=self.team, distinct_ids=["id_a", "id_b"], properties={"email": "multi@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["id_a", "id_b"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "id_a" in results
        assert "id_b" in results
        assert results["id_a"]["uuid"] == results["id_b"]["uuid"]

    def test_empty_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": []},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == {}
        self._assert_personhog_not_called("get_persons_by_distinct_ids_in_team")

    def test_invalid_input(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": "not_a_list"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["results"] == {}
        self._assert_personhog_not_called("get_persons_by_distinct_ids_in_team")

    def test_cross_team_isolation(self):
        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        self._seed_person(team=other_team, distinct_ids=["other_team_user"], properties={"email": "other@example.com"})
        self._seed_person(team=self.team, distinct_ids=["my_team_user"], properties={"email": "mine@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["my_team_user", "other_team_user"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert "my_team_user" in results
        assert "other_team_user" not in results

    def test_truncates_at_max_batch_size(self):
        distinct_ids = [f"user_{i}" for i in range(201)]
        self._seed_person(team=self.team, distinct_ids=[distinct_ids[200]], properties={"email": "last@example.com"})

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": distinct_ids},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert distinct_ids[200] not in results


class TestDestroyPerson(PersonhogTestMixin, APIBaseTest):
    def test_destroy_returns_202(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.delete(f"/api/person/{person.uuid}/")

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.content == b""
        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert list(calls[0].request.person_uuids) == [str(person.uuid)]

    def test_destroy_removes_person_from_postgres(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1", "did-2"])

        self.client.delete(f"/api/person/{person.uuid}/")

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert list(calls[0].request.person_uuids) == [str(person.uuid)]

    def test_destroy_nonexistent_returns_404(self):
        resp = self.client.delete(f"/api/person/{UUID_NONEXISTENT}/")

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        self._assert_personhog_not_called("delete_persons")

    def test_destroy_with_keep_person_skips_delete(self):
        person = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.delete(f"/api/person/{person.uuid}/?keep_person=true&delete_events=true")

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert get_person_by_uuid(self.team.pk, str(person.uuid)) is not None
        self._assert_personhog_not_called("delete_persons")


class TestBulkDeletePersons(PersonhogTestMixin, APIBaseTest):
    def _authenticate_psak(self, scopes: list[str] | None = None) -> None:
        token = generate_random_token_secret()
        ProjectSecretAPIKey.objects.create(
            team=self.team,
            label=f"Person deletion {ProjectSecretAPIKey.objects.filter(team=self.team).count()}",
            secure_value=hash_key_value(token),
            scopes=["person:write"] if scopes is None else scopes,
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @parameterized.expand([(False, False), (True, False), (False, True), (True, True)])
    def test_psak_bulk_delete_without_user(self, queued: bool, keep_person: bool) -> None:
        person = self._seed_person(team=self.team, distinct_ids=["delete-me"])
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_person = self._seed_person(team=other_team, distinct_ids=["delete-me"])
        self._authenticate_psak()
        temporal = mock.Mock(start_workflow=mock.AsyncMock())

        with (
            override_settings(PERSON_BULK_DELETE_ASYNC=queued),
            mock.patch("posthog.models.person.bulk_delete.sync_connect", return_value=temporal),
        ):
            result = self.client.post(
                f"/api/projects/{self.team.pk}/persons/bulk_delete/",
                {
                    "distinct_ids": ["delete-me"],
                    "keep_person": keep_person,
                    "delete_events": True,
                    "delete_recordings": True,
                },
                format="json",
            )

        assert result.status_code == 202, result.json()
        assert ActivityLog.objects.filter(team_id=self.team.pk, activity="bulk_delete_requested").count() == 1
        data = result.json()
        assert data["persons_found"] == 1
        assert data["persons_deleted"] == int(not queued and not keep_person)
        assert data["persons_queued_for_deletion"] == int(queued and not keep_person)
        assert data["deletion_errors"] == []
        assert data["events_queued_for_deletion"] is True
        assert data["recordings_queued_for_deletion"] is True
        assert (get_person_by_uuid(self.team.pk, str(person.uuid)) is not None) == keep_person
        assert get_person_by_uuid(other_team.pk, str(other_person.uuid)) is not None
        deletion = AsyncDeletion.objects.get(team_id=self.team.pk, key=str(person.uuid))
        assert deletion.deletion_type == DeletionType.Person
        assert deletion.created_by_id is None
        logs = ActivityLog.objects.filter(team_id=self.team.pk, scope="Person", activity="deleted")
        if keep_person:
            assert not logs.exists()
        else:
            log = logs.get(item_id=str(person.pk))
            assert log.user_id is None
            assert log.organization_id == self.organization.pk
        assert len(temporal.start_workflow.call_args_list) == 1
        workflow_name, payload = temporal.start_workflow.call_args.args
        assert workflow_name == "delete-recordings-with-person"
        assert payload.team_id == self.team.pk
        assert payload.distinct_ids == ["delete-me"]
        assert payload.config.deleted_by == "system"

    @parameterized.expand([(False, False), (True, False), (False, True), (True, True)])
    def test_psak_bulk_delete_records_request_without_matching_persons(self, queued: bool, impersonated: bool) -> None:
        self._authenticate_psak()
        key = ProjectSecretAPIKey.objects.get(team=self.team)
        if impersonated:
            session = self.client.session
            session[loginas_settings.USER_SESSION_FLAG] = TimestampSigner().sign(str(self.user.pk))
            session.save()

        with override_settings(PERSON_BULK_DELETE_ASYNC=queued):
            result = self.client.post(
                f"/api/projects/{self.team.pk}/persons/bulk_delete/",
                {"distinct_ids": ["missing-person"]},
                format="json",
            )

        assert result.status_code == 202, result.json()
        log = ActivityLog.objects.get(team_id=self.team.pk, scope="Person", activity="bulk_delete_requested")
        assert log.user_id is None
        assert log.credential_type == "project_secret_key"
        assert log.credential_id == key.id
        assert log.ip_address == "127.0.0.1"
        assert log.was_impersonated is False
        assert log.organization_id == self.organization.pk
        assert not ActivityLog.objects.filter(team_id=self.team.pk, activity="deleted").exists()

    @parameterized.expand([("missing_scope",), ("other_project",), ("no_auth",)])
    def test_psak_bulk_delete_rejects_unauthorized_requests(self, case: str) -> None:
        target_team = self.team
        if case == "other_project":
            target_team = Team.objects.create(organization=self.organization, name="Other project")
        person = self._seed_person(team=target_team, distinct_ids=["delete-me"])
        self._authenticate_psak(["endpoint:read"] if case == "missing_scope" else None)
        if case == "no_auth":
            self.client.credentials()

        result = self.client.post(
            f"/api/projects/{target_team.pk}/persons/bulk_delete/",
            {"distinct_ids": ["delete-me"]},
            format="json",
        )

        assert result.status_code in (401, 403), result.json()
        assert get_person_by_uuid(target_team.pk, str(person.uuid)) is not None
        assert not ActivityLog.objects.filter(scope="Person", activity="deleted").exists()

    @parameterized.expand([("get", ""), ("delete", "{uuid}/"), ("post", "{uuid}/delete_events/")])
    def test_psak_cannot_access_other_person_actions(self, method: str, suffix: str) -> None:
        person = self._seed_person(team=self.team, distinct_ids=["keep-me"])
        self._authenticate_psak()

        result = getattr(self.client, method)(f"/api/projects/{self.team.pk}/persons/{suffix.format(uuid=person.uuid)}")

        assert result.status_code == 403, result.json()
        assert "does not support project secret" in result.json()["detail"]
        assert get_person_by_uuid(self.team.pk, str(person.uuid)) is not None
        assert not AsyncDeletion.objects.filter(team_id=self.team.pk).exists()

    @parameterized.expand([("per_key", "1/minute", "100/minute"), ("per_project", "100/minute", "1/minute")])
    def test_psak_bulk_delete_is_throttled(self, case: str, key_rate: str, team_rate: str) -> None:
        cache.clear()
        person = self._seed_person(team=self.team, distinct_ids=["keep-me"])
        self._authenticate_psak()
        url = f"/api/projects/{self.team.pk}/persons/bulk_delete/"
        with (
            override_instance_config("RATE_LIMIT_ENABLED", True),
            mock.patch.object(PersonsDeleteBurstThrottle, "rate", key_rate),
            mock.patch.object(PersonsDeleteTeamBurstThrottle, "rate", team_rate),
        ):
            first = self.client.post(url, {"distinct_ids": ["missing"]}, format="json")
            assert first.status_code == 202, first.json()
            if case == "per_project":
                self._authenticate_psak()
            second = self.client.post(url, {"distinct_ids": ["keep-me"]}, format="json")

        assert second.status_code == 429, second.json()
        assert get_person_by_uuid(self.team.pk, str(person.uuid)) is not None

    def test_bulk_delete_by_ids(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["did-2"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"ids": [str(p1.uuid), str(p2.uuid)]},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 2
        assert data["persons_deleted"] == 2
        assert data["persons_queued_for_deletion"] == 0
        assert data["deletion_errors"] == []
        assert data["events_queued_for_deletion"] is False
        assert data["recordings_queued_for_deletion"] is False

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert set(calls[0].request.person_uuids) == {str(p1.uuid), str(p2.uuid)}

    @parameterized.expand([("by_ids",), ("by_distinct_ids",)])
    @override_settings(PERSON_BULK_DELETE_ASYNC=True)
    def test_bulk_delete_async_queues_persons_and_deletes_in_background(self, lookup):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["did-2"])
        payload = {"ids": [str(p1.uuid), str(p2.uuid)]} if lookup == "by_ids" else {"distinct_ids": ["did-1", "did-2"]}

        resp = self.client.post("/api/person/bulk_delete/", payload)

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 2
        assert data["persons_deleted"] == 0
        assert data["persons_queued_for_deletion"] == 2
        assert data["deletion_errors"] == []

        # The request must not batch-fetch distinct IDs; only the task pages through them.
        self._assert_personhog_not_called("get_distinct_ids_for_persons")
        self._assert_personhog_called("get_distinct_ids_for_person")
        # Celery runs eagerly in tests, so the queued task has already deleted the persons.
        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert set(calls[0].request.person_uuids) == {str(p1.uuid), str(p2.uuid)}
        assert get_person_by_uuid(self.team.pk, str(p1.uuid)) is None
        assert get_person_by_uuid(self.team.pk, str(p2.uuid)) is None
        # The task rebuilds the actor and organization from serialized ids; the log row proves it did.
        logs = ActivityLog.objects.filter(team_id=self.team.pk, scope="Person", activity="deleted")
        assert {log.item_id for log in logs} == {str(p1.pk), str(p2.pk)}
        assert {(log.user_id, log.organization_id) for log in logs} == {(self.user.pk, self.organization.id)}

    @override_settings(PERSON_BULK_DELETE_ASYNC=True)
    @mock.patch("posthog.api.person.queue_person_deletion")
    def test_single_person_delete_stays_synchronous_under_the_flag(self, queue_deletion):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.delete(f"/api/person/{p1.uuid}/")

        assert resp.status_code == status.HTTP_202_ACCEPTED
        queue_deletion.assert_not_called()
        self._assert_personhog_called("delete_persons")
        assert get_person_by_uuid(self.team.pk, str(p1.uuid)) is None

    @override_settings(PERSON_BULK_DELETE_ASYNC=True)
    @mock.patch("posthog.models.person.bulk_delete.queue_person_training_deletion")
    @mock.patch("posthog.api.person.queue_person_training_deletion")
    def test_bulk_delete_async_queues_training_deletion_once_per_distinct_id(self, request_side, task_side):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1", "did-2"])

        resp = self.client.post("/api/person/bulk_delete/", {"distinct_ids": ["did-1", "ghost"]})

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.json()["persons_found"] == 1
        # Nothing runs the replay session lookup in the request. The task queues the person's full
        # set once and the requested ID that matched no person once.
        request_side.assert_not_called()
        assert sorted(sorted(call.args[1]) for call in task_side.call_args_list) == [["did-1", "did-2"], ["ghost"]]
        assert get_person_by_uuid(self.team.pk, str(p1.uuid)) is None

    @override_settings(PERSON_BULK_DELETE_ASYNC=True)
    @mock.patch("posthog.models.person.bulk_delete.queue_person_training_deletion")
    def test_bulk_delete_async_queues_training_deletion_when_no_person_matches(self, task_side):
        resp = self.client.post("/api/person/bulk_delete/", {"distinct_ids": ["ghost"]})

        assert resp.status_code == status.HTTP_202_ACCEPTED
        assert resp.json()["persons_found"] == 0
        task_side.assert_called_once_with(self.team.pk, ["ghost"])

    @override_settings(PERSON_BULK_DELETE_ASYNC=True)
    def test_bulk_delete_async_keep_person_with_recordings(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1", "did-2"])
        # Snapshot at call time: the task releases each person's IDs once its batch has run.
        started: list[list[str]] = []

        with mock.patch(
            "posthog.models.person.bulk_delete._start_recording_workflows",
            side_effect=lambda _t, persons, *_a: started.extend(sorted(p.distinct_ids) for p in persons),
        ):
            resp = self.client.post(
                "/api/person/bulk_delete/",
                {"ids": [str(p1.uuid)], "keep_person": True, "delete_recordings": True},
            )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 1
        assert data["persons_queued_for_deletion"] == 0
        assert data["recordings_queued_for_deletion"] is True
        self._assert_personhog_not_called("get_distinct_ids_for_persons")
        assert started == [["did-1", "did-2"]]
        assert get_person_by_uuid(self.team.pk, str(p1.uuid)) is not None
        self._assert_personhog_not_called("delete_persons")

    def test_bulk_delete_by_distinct_ids(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])
        p2 = self._seed_person(team=self.team, distinct_ids=["did-2"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"distinct_ids": ["did-1", "did-2"]},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 2
        assert data["persons_deleted"] == 2
        assert data["deletion_errors"] == []

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert set(calls[0].request.person_uuids) == {str(p1.uuid), str(p2.uuid)}

    def test_bulk_delete_with_keep_person(self):
        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"ids": [str(p1.uuid)], "keep_person": True, "delete_events": True},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 1
        assert data["persons_deleted"] == 0
        assert data["events_queued_for_deletion"] is True
        assert data["deletion_errors"] == []
        assert get_person_by_uuid(self.team.pk, str(p1.uuid)) is not None
        self._assert_personhog_not_called("delete_persons")

    def test_cross_team_isolation(self):
        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_person = self._seed_person(team=other_team, distinct_ids=["other-did"])

        p1 = self._seed_person(team=self.team, distinct_ids=["did-1"])

        resp = self.client.post(
            "/api/person/bulk_delete/",
            {"ids": [str(p1.uuid)]},
        )

        assert resp.status_code == status.HTTP_202_ACCEPTED
        data = resp.json()
        assert data["persons_found"] == 1
        assert data["persons_deleted"] == 1
        assert data["deletion_errors"] == []

        calls = self._assert_personhog_called("delete_persons")
        if calls:
            assert calls[0].request.team_id == self.team.pk
            assert list(calls[0].request.person_uuids) == [str(p1.uuid)]
        # Other team's person should be untouched
        assert get_person_by_uuid(other_team.pk, str(other_person.uuid)) is not None
