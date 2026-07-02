import json
from typing import Optional, cast
from uuid import UUID, uuid4

import pytest
from freezegun.api import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    also_test_with_materialized_columns,
    flush_persons_and_events,
    override_settings,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries_context,
)
from unittest import mock

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

import posthog.models.person.deletion
from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import Organization, Person, PropertyDefinition, Team
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.person.missing_person import uuidFromDistinctId
from posthog.models.person.sql import PERSON_DISTINCT_ID2_TABLE
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    create_person_distinct_id,
    get_person_by_distinct_id,
    get_person_by_id,
    get_person_by_uuid,
)
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.test.persons import add_distinct_id, create_person, delete_person

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.cohorts.backend.models.cohort import Cohort


class TestPerson(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_legacy_get_person_by_id(self) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id"],
            properties={"email": "someone@gmail.com"},
            immediate=True,
        )
        flush_persons_and_events()

        # with self.assertNumQueries(7):
        response = self.client.get(f"/api/person/{person.pk}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], person.pk)

    @also_test_with_materialized_columns(event_properties=["email"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_search(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id"],
            properties={"email": "someone@gmail.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com", "name": "james"},
        )
        _create_person(team=self.team, distinct_ids=["distinct_id_3"], properties={"name": "jane"})

        flush_persons_and_events()
        response = self.client.get("/api/person/?search=another@gm")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

        response = self.client.get("/api/person/?search=distinct_id_3")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    @also_test_with_materialized_columns(event_properties=["email"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_search_person_id(self) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id"],
            properties={"email": "someone@gmail.com"},
        )
        flush_persons_and_events()
        response = self.client.get(f"/api/person/?search={person.uuid}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    @also_test_with_materialized_columns(event_properties=["email"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_properties(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id"],
            properties={"email": "someone@gmail.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com"},
        )
        _create_person(team=self.team, distinct_ids=["distinct_id_3"], properties={})
        flush_persons_and_events()

        response = self.client.get(
            "/api/person/?properties={}".format(
                json.dumps(
                    [
                        {
                            "key": "email",
                            "operator": "is_set",
                            "value": "is_set",
                            "type": "person",
                        }
                    ]
                )
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

        response = self.client.get(
            "/api/person/?properties={}".format(
                json.dumps(
                    [
                        {
                            "key": "email",
                            "operator": "icontains",
                            "value": "another@gm",
                            "type": "person",
                        }
                    ]
                )
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)

    @also_test_with_materialized_columns(person_properties=["random_prop"])
    @snapshot_clickhouse_queries
    def test_person_property_values(self):
        _create_person(
            distinct_ids=["person_1"],
            team=self.team,
            properties={"random_prop": "asdf", "some other prop": "with some text"},
        )
        _create_person(
            distinct_ids=["person_2"],
            team=self.team,
            properties={"random_prop": "asdf"},
        )
        _create_person(
            distinct_ids=["person_3"],
            team=self.team,
            properties={"random_prop": "qwerty"},
        )
        _create_person(
            distinct_ids=["person_4"],
            team=self.team,
            properties={"something_else": "qwerty"},
        )
        flush_persons_and_events()

        response = self.client.get("/api/person/values/?key=random_prop")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()["results"]
        self.assertEqual(response_data[0]["name"], "asdf")
        self.assertEqual(response_data[0]["count"], 2)
        self.assertEqual(response_data[1]["name"], "qwerty")
        self.assertEqual(response_data[1]["count"], 1)
        self.assertEqual(len(response_data), 2)

        response = self.client.get("/api/person/values/?key=random_prop&value=qw")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"][0]["name"], "qwerty")
        self.assertEqual(response.json()["results"][0]["count"], 1)

    @parameterized.expand(
        [
            ("default", "", "RECENT_CACHE_CALCULATE_ASYNC_IF_STALE_AND_BLOCKING_ON_MISS"),
            ("refresh_force_blocking", "refresh=force_blocking", "CALCULATE_BLOCKING_ALWAYS"),
            ("refresh_force_cache", "refresh=force_cache", "CACHE_ONLY_NEVER_CALCULATE"),
            ("refresh_async", "refresh=async", "RECENT_CACHE_CALCULATE_ASYNC_IF_STALE"),
        ]
    )
    @freeze_time("2020-01-10")
    def test_person_property_values_refresh(self, _name, param, expected_mode_name):
        from posthog.hogql_queries.property_values_query_runner import PropertyValuesQueryResponse
        from posthog.hogql_queries.query_runner import ExecutionMode

        _create_person(distinct_ids=["u1"], team=self.team, properties={"country": "US"})
        flush_persons_and_events()

        url = "/api/person/values/?key=country"
        if param:
            url += f"&{param}"

        with mock.patch(
            "posthog.hogql_queries.property_values_query_runner.PropertyValuesQueryRunner.run",
            return_value=PropertyValuesQueryResponse(results=[]),
        ) as mock_run:
            self.client.get(url)
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            assert args[0] == ExecutionMode[expected_mode_name]
            assert "analytics_props" in kwargs

    @also_test_with_materialized_columns(event_properties=["email"], person_properties=["email"])
    @snapshot_clickhouse_queries
    def test_filter_person_email(self):
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id", "another_one"],
            properties={"email": "someone@gmail.com"},
            is_identified=True,
            immediate=True,
        )
        person2: Person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com"},
            immediate=True,
        )
        flush_persons_and_events()

        # Filter
        response = self.client.get("/api/person/?email=another@gmail.com")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person2.uuid))
        self.assertEqual(response.json()["results"][0]["uuid"], str(person2.uuid))
        self.assertEqual(response.json()["results"][0]["properties"]["email"], "another@gmail.com")
        self.assertEqual(response.json()["results"][0]["distinct_ids"], ["distinct_id_2"])

    @snapshot_clickhouse_queries
    def test_filter_person_prop(self):
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id", "another_one"],
            properties={"email": "someone@gmail.com"},
            is_identified=True,
            immediate=True,
        )
        person2: Person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com", "some_prop": "some_value"},
            immediate=True,
        )
        flush_persons_and_events()

        # Filter
        response = self.client.get(
            "/api/person/?properties={}".format(
                json.dumps([{"key": "some_prop", "value": "some_value", "type": "person"}])
            )
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person2.uuid))
        self.assertEqual(response.json()["results"][0]["uuid"], str(person2.uuid))

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    @snapshot_clickhouse_queries
    def test_filter_person_list(self):
        person1: Person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id", "another_one"],
            properties={"email": "someone@gmail.com"},
            is_identified=True,
            immediate=True,
        )
        person2: Person = _create_person(
            team=self.team,
            distinct_ids=["distinct_id_2"],
            properties={"email": "another@gmail.com"},
            immediate=True,
        )
        flush_persons_and_events()

        # Filter by distinct ID
        # with self.assertNumQueries(11):
        response = self.client.get("/api/person/?distinct_id=distinct_id")  # must be exact matches
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person1.uuid))

        response = self.client.get("/api/person/?distinct_id=another_one")  # can search on any of the distinct IDs
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person1.uuid))

        # Filter by email
        response = self.client.get("/api/person/?email=another@gmail.com")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["id"], str(person2.uuid))

        # Non-matches return an empty list
        response = self.client.get("/api/person/?email=inexistent")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 0)

        response = self.client.get("/api/person/?distinct_id=inexistent")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 0)

    def test_cant_see_another_organization_pii_with_filters(self):
        # Completely different organization
        another_org: Organization = Organization.objects.create()
        another_team: Team = Team.objects.create(organization=another_org)
        _create_person(team=another_team, distinct_ids=["distinct_id", "x_another_one"])
        _create_person(
            team=another_team,
            distinct_ids=["x_distinct_id_2"],
            properties={"email": "team2_another@gmail.com"},
        )

        # Person in current team
        person: Person = _create_person(team=self.team, distinct_ids=["distinct_id"], immediate=True)

        # Filter by distinct ID
        response = self.client.get("/api/person/?distinct_id=distinct_id")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(
            response.json()["results"][0]["id"], str(person.uuid)
        )  # note that even with shared distinct IDs, only the person from the same team is returned

        response = self.client.get("/api/person/?distinct_id=x_another_one")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_delete_person(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        with snapshot_postgres_queries_context(
            self,
            custom_query_matcher=lambda query: (
                f"DELETE FROM posthog_person WHERE team_id = {self.team.pk} AND id = {person.pk}" in query
            ),
        ):
            response = self.client.delete(f"/api/person/{person.uuid}/")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.content, b"")  # Empty response
        self.assertIsNone(get_person_by_uuid(self.team.pk, str(person.uuid)))

        response = self.client.delete(f"/api/person/{person.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        self._assert_person_activity(
            person_id=None,  # can't query directly for deleted person
            expected=[
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "deleted",
                    "scope": "Person",
                    "item_id": str(person.pk),
                    # don't store deleted person's name, so user primary key
                    "detail": {
                        "changes": None,
                        "trigger": None,
                        "type": None,
                        "name": str(person.uuid),
                        "short_id": None,
                    },
                    "created_at": "2021-08-25T22:09:14.252000Z",
                }
            ],
        )

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)
        # No async deletion is scheduled
        self.assertEqual(AsyncDeletion.objects.filter(team_id=self.team.id).count(), 0)
        ch_events = sync_execute(
            "SELECT count() FROM events WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )[0][0]
        self.assertEqual(ch_events, 3)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_delete_person_and_events(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        response = self.client.delete(f"/api/person/{person.uuid}/?delete_events=true")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.content, b"")  # Empty response
        self.assertIsNone(get_person_by_uuid(self.team.pk, str(person.uuid)))

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)

        # async deletion scheduled and executed
        async_deletion = cast(AsyncDeletion, AsyncDeletion.objects.filter(team_id=self.team.id).first())
        self.assertEqual(async_deletion.deletion_type, DeletionType.Person)
        self.assertEqual(async_deletion.key, str(person.uuid))
        self.assertIsNone(async_deletion.delete_verified_at)

    @freeze_time("2021-08-25T22:09:14.252Z")
    @mock.patch("posthog.api.person.queue_person_recording_deletion")
    def test_delete_person_and_recordings(self, _mock_queue_delete):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
            immediate=True,
        )

        response = self.client.delete(f"/api/person/{person.uuid}/?delete_recordings=true&delete_events=true")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.content, b"")  # Empty response
        self.assertIsNone(get_person_by_uuid(self.team.pk, str(person.uuid)))

    @freeze_time("2021-08-25T22:09:14.252Z")
    @mock.patch("posthog.api.person.queue_person_recording_deletion")
    def test_delete_person_and_recordings_and_events(self, _mock_queue_delete):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        response = self.client.delete(f"/api/person/{person.uuid}/?delete_recordings=true&delete_events=true")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.content, b"")  # Empty response
        self.assertIsNone(get_person_by_uuid(self.team.pk, str(person.uuid)))

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)

        # async deletion scheduled and executed
        async_deletion = cast(AsyncDeletion, AsyncDeletion.objects.filter(team_id=self.team.id).first())
        self.assertEqual(async_deletion.deletion_type, DeletionType.Person)
        self.assertEqual(async_deletion.key, str(person.uuid))
        self.assertIsNone(async_deletion.delete_verified_at)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_bulk_delete_ids(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        person2 = _create_person(
            team=self.team,
            distinct_ids=["person_2", "anonymous_id_2"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        response = self.client.post(
            f"/api/person/bulk_delete/", {"ids": [person.uuid, person2.uuid], "delete_events": True}
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        data = response.json()
        self.assertEqual(data["persons_found"], 2)
        self.assertEqual(data["persons_deleted"], 2)
        self.assertTrue(data["events_queued_for_deletion"])
        self.assertFalse(data["recordings_queued_for_deletion"])
        self.assertEqual(data["deletion_errors"], [])
        self.assertIsNone(get_person_by_uuid(self.team.pk, str(person.uuid)))
        self.assertIsNone(get_person_by_uuid(self.team.pk, str(person2.uuid)))

        response = self.client.delete(f"/api/person/{person.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)

        # async deletion scheduled and executed
        async_deletion = cast(AsyncDeletion, AsyncDeletion.objects.filter(team_id=self.team.id).first())
        self.assertEqual(async_deletion.deletion_type, DeletionType.Person)
        self.assertEqual(async_deletion.key, str(person.uuid))
        self.assertIsNone(async_deletion.delete_verified_at)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_bulk_delete_distinct_id(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_person(
            team=self.team,
            distinct_ids=["person_2", "anonymous_id_2"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        response = self.client.post(f"/api/person/bulk_delete/", {"distinct_ids": ["anonymous_id", "person_2"]})

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED, response.content)
        data = response.json()
        self.assertEqual(data["persons_found"], 2)
        self.assertEqual(data["persons_deleted"], 2)
        self.assertFalse(data["events_queued_for_deletion"])
        self.assertFalse(data["recordings_queued_for_deletion"])
        self.assertEqual(data["deletion_errors"], [])
        self.assertIsNone(get_person_by_uuid(self.team.pk, str(person.uuid)))
        self.assertIsNone(get_person_by_distinct_id(self.team.pk, "person_2"))

        response = self.client.delete(f"/api/person/{person.uuid}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        ch_persons = sync_execute(
            "SELECT version, is_deleted, properties FROM person FINAL WHERE team_id = %(team_id)s and id = %(uuid)s",
            {"team_id": self.team.pk, "uuid": person.uuid},
        )
        self.assertEqual([(100, 1, "{}")], ch_persons)
        # No async deletion is scheduled
        self.assertEqual(AsyncDeletion.objects.filter(team_id=self.team.id).count(), 0)
        ch_events = sync_execute(
            "SELECT count() FROM events WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )[0][0]
        self.assertEqual(ch_events, 3)

    def test_bulk_delete_with_keep_person(self):
        """Test that bulk_delete with keep_person=True doesn't delete the person record"""
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        flush_persons_and_events()

        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"ids": [person.uuid], "delete_events": True, "keep_person": True},
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertEqual(data["persons_found"], 1)
        self.assertEqual(data["persons_deleted"], 0)
        self.assertTrue(data["events_queued_for_deletion"])
        self.assertEqual(data["deletion_errors"], [])
        # Person should still exist
        self.assertIsNotNone(get_person_by_uuid(self.team.pk, str(person.uuid)))
        # But async deletion for events should be scheduled
        async_deletion = cast(AsyncDeletion, AsyncDeletion.objects.filter(team_id=self.team.id).first())
        self.assertIsNotNone(async_deletion)
        self.assertEqual(async_deletion.deletion_type, DeletionType.Person)
        self.assertEqual(async_deletion.key, str(person.uuid))

    @mock.patch("posthog.api.person.queue_person_recording_deletion")
    def test_bulk_delete_with_recordings(self, _mock_queue_delete):
        """Test that bulk_delete queues recording deletion"""
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1"],
            properties={"$os": "Chrome"},
            immediate=True,
        )

        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"ids": [person.uuid], "delete_recordings": True},
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertEqual(data["persons_found"], 1)
        self.assertEqual(data["persons_deleted"], 1)
        self.assertFalse(data["events_queued_for_deletion"])
        self.assertTrue(data["recordings_queued_for_deletion"])
        self.assertEqual(data["deletion_errors"], [])

    def test_bulk_delete_validation_too_many_ids(self):
        """Test that bulk_delete rejects more than 1000 IDs"""
        # Test with ids
        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"ids": [str(uuid4()) for _ in range(1001)]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("1000", str(response.content))

        # Test with distinct_ids
        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"distinct_ids": [f"id_{i}" for i in range(1001)]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("1000", str(response.content))

    def test_bulk_delete_validation_missing_ids(self):
        """Test that bulk_delete requires either ids or distinct_ids"""
        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"delete_events": True},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("distinct_ids or ids", str(response.content))

    def test_bulk_delete_validation_rejects_both_ids_and_distinct_ids(self):
        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"ids": [str(uuid4())], "distinct_ids": ["did_1"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not both", str(response.content))

    def test_bulk_delete_no_matching_persons(self):
        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"ids": [str(uuid4()), str(uuid4())], "delete_events": True},
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertEqual(data["persons_found"], 0)
        self.assertEqual(data["persons_deleted"], 0)
        self.assertFalse(data["events_queued_for_deletion"])
        self.assertEqual(data["deletion_errors"], [])
        self.assertEqual(AsyncDeletion.objects.filter(team_id=self.team.id).count(), 0)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_deletion_status_lists_pending_deletions(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1"],
            properties={"$os": "Chrome"},
            immediate=True,
        )

        self.client.post(
            f"/api/person/bulk_delete/",
            {"ids": [person.uuid], "delete_events": True},
        )

        response = self.client.get(f"/api/person/deletion_status/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["person_uuid"], str(person.uuid))
        self.assertEqual(data["results"][0]["status"], "pending")
        self.assertIsNone(data["results"][0]["delete_verified_at"])

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_deletion_status_filters_by_status(self):
        person1 = _create_person(
            team=self.team,
            distinct_ids=["person_1"],
            immediate=True,
        )
        person2 = _create_person(
            team=self.team,
            distinct_ids=["person_2"],
            immediate=True,
        )

        # Create one pending and one completed deletion
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.team.id,
            key=str(person1.uuid),
        )
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.team.id,
            key=str(person2.uuid),
            delete_verified_at="2021-08-25T23:00:00Z",
        )

        # Filter pending
        response = self.client.get(f"/api/person/deletion_status/?status=pending")
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["person_uuid"], str(person1.uuid))
        self.assertEqual(data["results"][0]["status"], "pending")

        # Filter completed
        response = self.client.get(f"/api/person/deletion_status/?status=completed")
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["person_uuid"], str(person2.uuid))
        self.assertEqual(data["results"][0]["status"], "completed")

        # All
        response = self.client.get(f"/api/person/deletion_status/")
        data = response.json()
        self.assertEqual(data["count"], 2)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_deletion_status_filters_by_person_uuid(self):
        person1 = _create_person(
            team=self.team,
            distinct_ids=["person_1"],
            immediate=True,
        )
        person2 = _create_person(
            team=self.team,
            distinct_ids=["person_2"],
            immediate=True,
        )

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.team.id,
            key=str(person1.uuid),
        )
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.team.id,
            key=str(person2.uuid),
        )

        response = self.client.get(f"/api/person/deletion_status/?person_uuid={person1.uuid}")
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["person_uuid"], str(person1.uuid))

    @mock.patch("posthog.models.person.bulk_delete.delete_person")
    def test_bulk_delete_partial_failure(self, mock_delete_person):
        """Test that bulk_delete continues when a single person fails to delete and reports errors"""
        person1 = _create_person(
            team=self.team,
            distinct_ids=["person_1"],
            immediate=True,
        )
        person2 = _create_person(
            team=self.team,
            distinct_ids=["person_2"],
            immediate=True,
        )

        # Make delete_person fail on the first person, succeed on the second
        mock_delete_person.side_effect = [Exception("DB connection lost"), None]

        response = self.client.post(
            f"/api/person/bulk_delete/",
            {"ids": [person1.uuid, person2.uuid]},
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertEqual(data["persons_found"], 2)
        self.assertEqual(data["persons_deleted"], 1)
        self.assertEqual(len(data["deletion_errors"]), 1)
        self.assertEqual(data["deletion_errors"][0]["person_uuid"], str(person1.uuid))
        self.assertNotIn("detail", data["deletion_errors"][0])

    def test_deletion_status_rejects_invalid_status(self):
        """Test that deletion_status returns 400 for invalid status filter"""
        response = self.client.get(f"/api/person/deletion_status/?status=invalid")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deletion_status_rejects_invalid_person_uuid(self):
        """Test that deletion_status returns 400 for non-UUID person_uuid"""
        response = self.client.get(f"/api/person/deletion_status/?person_uuid=not-a-uuid")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deletion_status_excludes_other_teams(self):
        other_team = Team.objects.create(organization=self.organization, name="other team")

        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=other_team.id,
            key=str(uuid4()),
        )
        AsyncDeletion.objects.create(
            deletion_type=DeletionType.Person,
            team_id=self.team.id,
            key=str(uuid4()),
        )

        response = self.client.get(f"/api/person/deletion_status/")
        data = response.json()
        self.assertEqual(data["count"], 1)

    def test_destroy_with_keep_person_param(self):
        """Test that destroy endpoint respects keep_person parameter"""
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1"],
            properties={"$os": "Chrome"},
            immediate=True,
        )

        response = self.client.delete(f"/api/person/{person.uuid}/?keep_person=true&delete_events=true")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        # Person should still exist when keep_person=true
        self.assertIsNotNone(get_person_by_uuid(self.team.pk, str(person.uuid)))
        # But async deletion should be scheduled
        self.assertEqual(AsyncDeletion.objects.filter(team_id=self.team.id).count(), 1)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_split_people_keep_props(self) -> None:
        # created first
        person1 = _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
        )

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person1.pk,
                uuid=str(person1.uuid),
                distinct_ids=["1", "2", "3"],
            )

            self.client.post("/api/person/{}/split/".format(person1.pk), {"main_distinct_id": "1"})

            split_calls = fake.assert_called("split_person", times=1)
            self.assertEqual(list(split_calls[0].request.distinct_ids_to_split), ["2", "3"])
            # "1" stays on the original; "2" and "3" each land on their own new person
            self.assertEqual(fake._persons_by_distinct_id[(self.team.id, "1")].id, person1.pk)
            moved = {did: fake._persons_by_distinct_id[(self.team.id, did)].id for did in ["2", "3"]}
            self.assertNotIn(person1.pk, moved.values())
            self.assertNotEqual(moved["2"], moved["3"])

        # Properties stay on the original person when a main_distinct_id is given
        self.assertEqual(person1.properties, {"$browser": "whatever", "$os": "Mac OS X"})

        self._assert_person_activity(
            person_id=person1.uuid,
            expected=[
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "split_person",
                    "scope": "Person",
                    "item_id": str(person1.pk),
                    "detail": {
                        "changes": [
                            {
                                "type": "Person",
                                "action": "split",
                                "field": None,
                                "before": None,
                                "after": {"distinct_ids": ["1", "2", "3"]},
                            }
                        ],
                        "name": str(person1.uuid),
                        "trigger": None,
                        "type": None,
                        "short_id": None,
                    },
                    "created_at": "2021-08-25T22:09:14.252000Z",
                }
            ],
        )

    def test_split_people_delete_props(self) -> None:
        # created first
        person1 = _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person1.pk,
                uuid=str(person1.uuid),
                distinct_ids=["1", "2", "3"],
            )

            response = self.client.post("/api/person/{}/split/".format(person1.pk))

            # Without a main_distinct_id the first distinct_id stays; the rest split off
            split_calls = fake.assert_called("split_person", times=1)
            self.assertEqual(list(split_calls[0].request.distinct_ids_to_split), ["2", "3"])
            self.assertEqual(fake._persons_by_distinct_id[(self.team.id, "1")].id, person1.pk)

        # Properties are always kept on the original person
        self.assertEqual(person1.properties, {"$browser": "whatever", "$os": "Mac OS X"})
        self.assertTrue(response.json()["success"])

    def test_split_people_partial_moves_only_specified_ids(self) -> None:
        person1 = _create_person(
            team=self.team,
            distinct_ids=["keep1", "move1", "keep2", "move2"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person1.pk,
                uuid=str(person1.uuid),
                distinct_ids=["keep1", "move1", "keep2", "move2"],
            )

            response = self.client.post(
                "/api/person/{}/split/".format(person1.pk),
                {"distinct_ids_to_split": ["move1", "move2"]},
            )
            self.assertEqual(response.status_code, 201, response.content)
            self.assertTrue(response.json()["success"])

            split_calls = fake.assert_called("split_person", times=1)
            self.assertEqual(list(split_calls[0].request.distinct_ids_to_split), ["move1", "move2"])

            # Kept distinct_ids stay on the original; each moved one lands on its own new person.
            for did in ["keep1", "keep2"]:
                self.assertEqual(fake._persons_by_distinct_id[(self.team.id, did)].id, person1.pk)
            moved = {did: fake._persons_by_distinct_id[(self.team.id, did)].id for did in ["move1", "move2"]}
            self.assertNotIn(person1.pk, moved.values())
            self.assertNotEqual(moved["move1"], moved["move2"])

        # The partial-split guarantee: the original person keeps its properties.
        original = get_person_by_id(self.team.id, person1.pk)
        assert original is not None
        self.assertEqual(original.properties, {"$browser": "whatever", "$os": "Mac OS X"})

    def test_split_people_partial_rejects_unknown_distinct_id(self) -> None:
        person1 = _create_person(
            team=self.team,
            distinct_ids=["a", "b"],
            properties={},
            immediate=True,
        )

        response = self.client.post(
            "/api/person/{}/split/".format(person1.pk),
            {"distinct_ids_to_split": ["a", "not_on_this_person"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not_on_this_person", response.content.decode())

        # Nothing should have moved.
        original = get_person_by_id(self.team.id, person1.pk)
        assert original is not None
        self.assertCountEqual(original.distinct_ids, ["a", "b"])

    def test_split_people_partial_rejects_combined_with_main_distinct_id(self) -> None:
        person1 = _create_person(
            team=self.team,
            distinct_ids=["a", "b", "c"],
            properties={},
            immediate=True,
        )

        response = self.client.post(
            "/api/person/{}/split/".format(person1.pk),
            {"distinct_ids_to_split": ["b"], "main_distinct_id": "a"},
        )
        self.assertEqual(response.status_code, 400)

    def test_split_people_partial_rejects_invalid_payload(self) -> None:
        person1 = _create_person(
            team=self.team,
            distinct_ids=["a", "b"],
            properties={},
            immediate=True,
        )

        # Empty list.
        response = self.client.post(
            "/api/person/{}/split/".format(person1.pk),
            {"distinct_ids_to_split": []},
        )
        self.assertEqual(response.status_code, 400)

        # Wrong type for the field.
        response = self.client.post(
            "/api/person/{}/split/".format(person1.pk),
            {"distinct_ids_to_split": "a"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

        # List with non-string entries.
        response = self.client.post(
            "/api/person/{}/split/".format(person1.pk),
            {"distinct_ids_to_split": [1, 2]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_update_multiple_person_properties_validation(self) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        response = self.client.patch(f"/api/person/{person.uuid}", {"foo": "bar", "bar": "baz"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            self.validation_error_response("required", "This field is required.", "properties"),
        )

    @mock.patch("posthog.api.person.capture_internal")
    def test_new_update_single_person_property(self, mock_capture) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        self.client.post(f"/api/person/{person.uuid}/update_property", {"key": "foo", "value": "bar"})

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$set",
            event_source="person_viewset",
            distinct_id="some_distinct_id",
            timestamp=mock.ANY,
            properties={
                "$set": {"foo": "bar"},
            },
            process_person_profile=True,
        )

    @mock.patch("posthog.api.person.capture_internal")
    def test_new_delete_person_properties(self, mock_capture) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        self.client.post(f"/api/person/{person.uuid}/delete_property", {"$unset": "foo"})

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$delete_person_property",
            event_source="person_viewset",
            distinct_id="some_distinct_id",
            timestamp=mock.ANY,
            properties={
                "$unset": ["foo"],
            },
            process_person_profile=True,
        )

    @mock.patch("posthog.api.person.capture_internal")
    def test_update_person_property_by_numeric_id(self, mock_capture) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        self.client.post(f"/api/person/{person.id}/update_property", {"key": "foo", "value": "bar"})

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$set",
            event_source="person_viewset",
            distinct_id="some_distinct_id",
            timestamp=mock.ANY,
            properties={
                "$set": {"foo": "bar"},
            },
            process_person_profile=True,
        )

    @mock.patch("posthog.api.person.capture_internal")
    def test_delete_person_property_by_numeric_id(self, mock_capture) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        self.client.post(f"/api/person/{person.id}/delete_property", {"$unset": "foo"})

        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$delete_person_property",
            event_source="person_viewset",
            distinct_id="some_distinct_id",
            timestamp=mock.ANY,
            properties={
                "$unset": ["foo"],
            },
            process_person_profile=True,
        )

    @mock.patch("posthog.api.person.capture_internal")
    def test_update_person_property_with_null_value(self, mock_capture) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        response = self.client.post(
            f"/api/person/{person.uuid}/update_property",
            {"key": "foo", "value": None},
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        mock_capture.assert_called_once_with(
            token=self.team.api_token,
            event_name="$set",
            event_source="person_viewset",
            distinct_id="some_distinct_id",
            timestamp=mock.ANY,
            properties={
                "$set": {"foo": None},
            },
            process_person_profile=True,
        )

    def test_update_person_property_missing_value_returns_400(self) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever"},
            immediate=True,
        )

        response = self.client.post(
            f"/api/person/{person.uuid}/update_property",
            {"key": "foo"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "value")

    def test_update_person_property_missing_key_returns_400(self) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["some_distinct_id"],
            properties={"$browser": "whatever"},
            immediate=True,
        )

        response = self.client.post(
            f"/api/person/{person.uuid}/update_property",
            {"value": "bar"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["attr"], "key")

    def test_return_non_anonymous_name(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=[
                "distinct_id1",
                "17787c3099427b-0e8f6c86323ea9-33647309-1aeaa0-17787c30995b7c",
            ],
        )
        _create_person(
            team=self.team,
            distinct_ids=[
                "17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c",
                "distinct_id2",
            ],
        )
        flush_persons_and_events()

        response = self.client.get("/api/person/").json()

        self.assertEqual(response["results"][0]["name"], "distinct_id2")
        self.assertEqual(response["results"][1]["name"], "distinct_id1")

        self.assertCountEqual(
            response["results"][0]["distinct_ids"],
            ["17787c327b-0e8f623ea9-336473-1aeaa0-17787c30995b7c", "distinct_id2"],
        )
        self.assertCountEqual(
            response["results"][1]["distinct_ids"],
            [
                "distinct_id1",
                "17787c3099427b-0e8f6c86323ea9-33647309-1aeaa0-17787c30995b7c",
            ],
        )

    def test_person_display_name(self) -> None:
        self.team.person_display_name_properties = ["custom_name", "custom_email"]
        self.team.save()
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id1"],
            properties={
                "custom_name": "someone",
                "custom_email": "someone@custom.com",
                "email": "someone@gmail.com",
            },
        )
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id2"],
            properties={
                "custom_email": "another_one@custom.com",
                "email": "another_one@gmail.com",
            },
        )
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id3"],
            properties={"email": "yet_another_one@gmail.com"},
        )
        flush_persons_and_events()

        response = self.client.get("/api/person/").json()

        results = response["results"][::-1]  # results are in reverse order
        self.assertEqual(results[0]["name"], "someone")
        self.assertEqual(results[1]["name"], "another_one@custom.com")
        self.assertEqual(results[2]["name"], "distinct_id3")

    def test_person_display_name_defaults(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id1"],
            properties={"name": "someone", "email": "someone@gmail.com"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id2"],
            properties={"name": "another_one"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["distinct_id3"],
        )
        flush_persons_and_events()

        response = self.client.get("/api/person/").json()

        results = response["results"][::-1]  # results are in reverse order
        self.assertEqual(results[0]["name"], "someone@gmail.com")
        self.assertEqual(results[1]["name"], "another_one")
        self.assertEqual(results[2]["name"], "distinct_id3")

    def test_person_cohorts(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team, name="number", property_type="Numeric", type=PropertyDefinition.Type.PERSON
        )
        _create_person(
            team=self.team,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "number": 1},
        )
        person2 = _create_person(
            team=self.team,
            distinct_ids=["2"],
            properties={"$some_prop": "something", "number": 2},
            immediate=True,
        )
        cohort1 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        cohort2 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "number", "value": 1, "type": "person"}]}],
            name="cohort2",
        )
        cohort3 = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "number", "value": 2, "type": "person"}]}],
            name="cohort3",
        )
        cohort1.calculate_people_ch(pending_version=0)
        cohort2.calculate_people_ch(pending_version=0)
        cohort3.calculate_people_ch(pending_version=0)

        cohort4 = Cohort.objects.create(
            team=self.team,
            groups=[],
            is_static=True,
            last_calculation=timezone.now(),
            name="cohort4",
        )
        cohort4.insert_users_by_list(["2"])

        response = self.client.get(f"/api/person/cohorts/?person_id={person2.uuid}").json()
        response["results"].sort(key=lambda cohort: cohort["name"])
        self.assertEqual(len(response["results"]), 3)
        self.assertLessEqual(
            {"id": cohort1.id, "count": 2, "name": cohort1.name}.items(), response["results"][0].items()
        )
        self.assertLessEqual(
            {"id": cohort3.id, "count": 1, "name": cohort3.name}.items(), response["results"][1].items()
        )
        self.assertLessEqual(
            {"id": cohort4.id, "count": 1, "name": cohort4.name}.items(), response["results"][2].items()
        )

    def test_person_cohorts_with_cohort_version(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team, name="number", property_type="Numeric", type=PropertyDefinition.Type.PERSON
        )
        person = _create_person(
            team=self.team,
            distinct_ids=["1"],
            properties={"$some_prop": "something", "number": 1},
        )

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )

        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(f"/api/person/cohorts/?person_id={person.uuid}").json()
        self.assertEqual(len(response["results"]), 1)
        self.assertLessEqual({"id": cohort.id, "count": 1, "name": cohort.name}.items(), response["results"][0].items())

        # Update the group to no longer include person
        cohort.groups = [{"properties": [{"key": "no", "value": "no", "type": "person"}]}]
        cohort.save()
        cohort.calculate_people_ch(pending_version=1)

        response = self.client.get(f"/api/person/cohorts/?person_id={person.uuid}").json()
        self.assertEqual(len(response["results"]), 0)

    def test_person_cohorts_returns_minimal_fields(self) -> None:
        """Verify that person cohorts endpoint returns only minimal fields (id, name, count)."""
        person = _create_person(
            team=self.team,
            distinct_ids=["1"],
            properties={"$some_prop": "something"},
            immediate=True,
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(f"/api/person/cohorts/?person_id={person.uuid}")
        self.assertEqual(response.status_code, 200, response.json())
        data = response.json()

        self.assertEqual(len(data["results"]), 1)
        # CohortMinimalSerializer only returns id, name, count
        self.assertEqual(set(data["results"][0].keys()), {"id", "name", "count"})

    def test_person_cohorts_via_nested_project_url(self) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["1"],
            properties={"$some_prop": "something"},
            immediate=True,
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
            name="cohort1",
        )
        cohort.calculate_people_ch(pending_version=0)

        response = self.client.get(f"/api/projects/{self.team.id}/persons/cohorts/?person_id={person.uuid}")
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["name"], "cohort1")

    def test_split_person_clickhouse(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.id,
                person_id=person.pk,
                uuid=str(person.uuid),
                distinct_ids=["1", "2", "3"],
            )

            response = self.client.post("/api/person/{}/split/".format(person.uuid)).json()
            self.assertTrue(response["success"])

        # ClickHouse ends up with the original person plus one new person per
        # split distinct_id, each with its deterministic UUID.
        expected_person_by_did = {
            "1": person.uuid,
            "2": uuidFromDistinctId(self.team.pk, "2"),
            "3": uuidFromDistinctId(self.team.pk, "3"),
        }
        clickhouse_people = sync_execute(
            "SELECT id FROM person FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )
        self.assertCountEqual(clickhouse_people, [(uuid,) for uuid in expected_person_by_did.values()])

        pdis2 = sync_execute(
            "SELECT person_id, distinct_id, is_deleted FROM person_distinct_id2 FINAL WHERE team_id = %(team_id)s",
            {"team_id": self.team.pk},
        )

        self.assertEqual(len(pdis2), 3)
        for distinct_id, expected_uuid in expected_person_by_did.items():
            matching_row = next(row for row in pdis2 if row[1] == distinct_id)
            self.assertEqual(matching_row, (expected_uuid, distinct_id, 0))

    def test_split_person_overrides_delete_version(self):
        """
        Test that split person correctly sets version to override deleted persons.

        When a person is deleted, the delete event uses version + 100 (e.g., version 100).
        When splitting, the new person should use version + 101 (e.g., version 101) to ensure
        ClickHouse sees the split person as more recent than the delete event.
        """
        # Create person A with UUID derived from the distinct_id (same UUID that split will use)
        person_a_uuid = uuidFromDistinctId(self.team.pk, "deleted_user")
        person_a = create_person(
            team=self.team,
            uuid=person_a_uuid,
            version=0,
        )
        add_distinct_id(person=person_a, distinct_id="deleted_user", version=0)
        create_person_in_ch(
            team_id=self.team.pk,
            uuid=str(person_a.uuid),
            version=0,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="deleted_user",
            person_id=str(person_a.uuid),
            version=0,
        )

        # Delete person A (this creates a delete event with version 100 = 0 + 100)
        delete_person(person_a)

        # Create person B with a different distinct_id (will also have version 0 by default)
        person_b = _create_person(
            team=self.team,
            distinct_ids=["active_user"],
            immediate=True,
        )

        # Manually add the deleted distinct_id to person B (simulating a merge scenario)
        # This would happen in a real scenario where events come in for the deleted distinct_id
        add_distinct_id(person=person_b, distinct_id="deleted_user", version=2)
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="deleted_user",
            person_id=str(person_b.uuid),
            version=2,
        )

        # Now person_b has both "active_user" and "deleted_user"
        self.assertEqual(set(person_b.distinct_ids), {"active_user", "deleted_user"})

        # Split person B
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=self.team.pk,
                person_id=person_b.pk,
                uuid=str(person_b.uuid),
                distinct_ids=["active_user", "deleted_user"],
                distinct_id_versions={"deleted_user": 2},
            )

            response = self.client.post("/api/person/{}/split/".format(person_b.uuid)).json()
            self.assertTrue(response["success"])

        # Verify ClickHouse has the correct state
        ch_persons = sync_execute(
            """
            SELECT id, version, is_deleted
            FROM person
            FINAL
            WHERE team_id = %(team_id)s AND id IN (
                SELECT DISTINCT person_id
                FROM person_distinct_id2
                FINAL
                WHERE team_id = %(team_id)s AND distinct_id = 'deleted_user'
            )
            ORDER BY version DESC
            """,
            {"team_id": self.team.pk},
        )

        # Should have exactly one person (the split creates a new one with version 101)
        self.assertEqual(len(ch_persons), 1)
        _, version, is_deleted = ch_persons[0]

        # The split person should have version 101 (person_b version 0 + 101)
        # which is higher than the delete version 100 (person_a version 0 + 100)
        self.assertEqual(version, 101)
        self.assertEqual(is_deleted, 0)

        # Verify person_distinct_id2 for the deleted_user distinct_id
        ch_pdis = sync_execute(
            """
            SELECT person_id, distinct_id, version, is_deleted
            FROM person_distinct_id2
            FINAL
            WHERE team_id = %(team_id)s AND distinct_id = 'deleted_user'
            """,
            {"team_id": self.team.pk},
        )

        self.assertEqual(len(ch_pdis), 1)
        _, pdi_distinct_id, _, pdi_is_deleted = ch_pdis[0]
        self.assertEqual(pdi_distinct_id, "deleted_user")
        self.assertEqual(pdi_is_deleted, 0)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_patch_user_property_activity(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
            immediate=True,
        )

        created_person = self.client.get("/api/person/{}/".format(person.uuid)).json()
        created_person["properties"]["a"] = "b"
        response = self.client.patch("/api/person/{}/".format(person.uuid), created_person)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        self.client.get("/api/person/{}/".format(person.uuid))

        self._assert_person_activity(
            person_id=person.uuid,
            expected=[
                {
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
                    "activity": "updated",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "Person",
                    "item_id": str(person.pk),
                    "detail": {
                        "changes": [
                            {
                                "type": "Person",
                                "action": "changed",
                                "field": "properties",
                                "before": None,
                                "after": None,
                            }
                        ],
                        "trigger": None,
                        "type": None,
                        "name": None,
                        "short_id": None,
                    },
                }
            ],
        )

    def test_csv_export(self):
        _create_person(
            team=self.team,
            distinct_ids=["1", "2", "3"],
            properties={"$browser": "whatever", "$os": "Mac OS X"},
        )
        _create_person(
            team=self.team,
            distinct_ids=["4"],
            properties={"$browser": "whatever", "$os": "Windows"},
        )

        flush_persons_and_events()
        response = self.client.get("/api/person.csv")
        self.assertEqual(len(response.content.splitlines()), 3, response.content)

        response = self.client.get(
            "/api/person.csv?properties={}".format(json.dumps([{"key": "$os", "value": "Windows", "type": "person"}]))
        )
        self.assertEqual(len(response.content.splitlines()), 2)

    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_pagination_limit(self):
        created_ids = []

        for index in range(0, 19):
            created_ids.append(str(index + 100))
            create_person(  # creating without _create_person to guarantee created_at ordering
                team=self.team,
                distinct_ids=[str(index + 100)],
                properties={"$browser": "whatever", "$os": "Windows"},
            )

        # Very occasionally, a person might be deleted in postgres but not in Clickhouse due to network issues or whatever
        # In this case Clickhouse will return a user that then doesn't get returned by postgres.
        # We would return an empty "next" url.
        # Now we just return 9 people instead
        create_person_in_ch(team_id=self.team.pk, version=0)

        returned_ids = []
        with self.assertNumQueries(16):
            response = self.client.get("/api/person/?limit=10").json()
        self.assertEqual(len(response["results"]), 9)
        returned_ids += [x["distinct_ids"][0] for x in response["results"]]
        response_next = self.client.get(response["next"]).json()
        returned_ids += [x["distinct_ids"][0] for x in response_next["results"]]
        self.assertEqual(len(response_next["results"]), 10)

        created_ids.reverse()  # ids are returned in desc order
        self.assertEqual(returned_ids, created_ids, returned_ids)

        with self.assertNumQueries(20):
            response_include_total = self.client.get("/api/person/?limit=10&include_total").json()
        self.assertEqual(response_include_total["count"], 20)  #  With `include_total`, the total count is returned too

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_pagination_no_gaps_or_duplicates_when_created_at_is_tied(self):
        # Bulk-created persons can share an identical created_at, so the `created_at DESC` ordering
        # falls to the `id DESC` tiebreaker. Page boundaries must stay disjoint and complete: every
        # person returned exactly once, with no gaps or duplicates across pages — the failure mode
        # that actually matters on this high-traffic paginated endpoint.
        uuids = [UUID(f"00000000-0000-0000-0000-0000000000{i:02d}") for i in range(1, 8)]
        for person_uuid in uuids:
            create_person(team=self.team, distinct_ids=[str(person_uuid)], uuid=person_uuid)

        expected = {str(person_uuid) for person_uuid in uuids}
        full = [row["id"] for row in self.client.get("/api/person/?limit=100").json()["results"]]
        self.assertEqual(set(full), expected)
        self.assertEqual(len(full), len(uuids))  # complete in a single page

        # Paging with a small limit must cover exactly the same set, once each.
        paged: list[str] = []
        url: Optional[str] = "/api/person/?limit=2"
        while url:
            page = self.client.get(url).json()
            paged += [row["id"] for row in page["results"]]
            url = page["next"]
        self.assertEqual(len(paged), len(uuids))  # no person lost or repeated at a page boundary
        self.assertEqual(set(paged), expected)  # union of pages == full set, gapless and dup-free

    def test_retrieve_person(self):
        person = create_person(  # creating without _create_person to guarantee created_at ordering
            team=self.team, distinct_ids=["123456789"]
        )

        response = self.client.get(f"/api/person/{person.id}").json()

        assert response["id"] == person.id
        assert response["uuid"] == str(person.uuid)
        assert response["distinct_ids"] == ["123456789"]

    def test_retrieve_person_by_uuid(self):
        person = create_person(  # creating without _create_person to guarantee created_at ordering
            team=self.team, distinct_ids=["123456789"]
        )

        response = self.client.get(f"/api/person/{person.uuid}").json()

        assert response["id"] == person.id
        assert response["uuid"] == str(person.uuid)
        assert response["distinct_ids"] == ["123456789"]

    def test_retrieve_person_by_distinct_id_with_useful_error(self):
        response = self.client.get(f"/api/person/NOT_A_UUID").json()

        assert (
            response["detail"]
            == "The ID provided does not look like a personID. If you are using a distinctId, please use /persons?distinct_id=NOT_A_UUID instead."
        )

    def _get_person_activity(
        self,
        person_id: Optional[str] = None,
        *,
        expected_status: int = status.HTTP_200_OK,
    ):
        if person_id:
            url = f"/api/person/{person_id}/activity"
        else:
            url = f"/api/person/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        return activity.json()

    def _assert_person_activity(self, person_id: Optional[str], expected: list[dict]):
        activity_response = self._get_person_activity(person_id)

        activity: list[dict] = activity_response["results"]
        for item in activity:
            item.pop("id", None)
        self.maxDiff = None
        self.assertCountEqual(activity, expected)

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_delete_events_only(self):
        person = _create_person(
            team=self.team,
            distinct_ids=["person_1", "anonymous_id"],
            properties={"$os": "Chrome"},
            immediate=True,
        )
        _create_event(event="test", team=self.team, distinct_id="person_1")
        _create_event(event="test", team=self.team, distinct_id="anonymous_id")
        _create_event(event="test", team=self.team, distinct_id="someone_else")

        flush_persons_and_events()

        response = self.client.post(f"/api/person/{person.uuid}/delete_events/")

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.content == b""  # Empty response

        # Person still exists
        self.assertIsNotNone(get_person_by_uuid(self.team.pk, str(person.uuid)))

        # async deletion scheduled
        async_deletion = cast(AsyncDeletion, AsyncDeletion.objects.filter(team_id=self.team.id).first())
        assert async_deletion.deletion_type == DeletionType.Person
        assert async_deletion.key == str(person.uuid)
        assert async_deletion.delete_verified_at is None

    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_delete_person_events_not_found(self):
        # Use a valid UUID that doesn't exist in the database
        non_existent_uuid = "11111111-1111-1111-1111-111111111111"

        response = self.client.post(f"/api/person/{non_existent_uuid}/delete_events/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["detail"] == "Not found."

    @pytest.mark.flaky(reruns=2)
    def test_reset_person_distinct_id(self):
        # Simulate the real-world scenario: person deleted in CH (soft delete with high version),
        # then the same distinct_id is reused which creates a new person in PG with the same
        # deterministic UUID. The new person's CH row has a lower version than the deletion,
        # so ReplacingMergeTree keeps the deleted state.
        shared_uuid = str(uuid4())

        # Phase 1: Person and distinct_id exist in CH as deleted
        create_person_in_ch(
            uuid=shared_uuid,
            team_id=self.team.pk,
            is_deleted=True,
            version=105,
        )
        create_person_distinct_id(
            team_id=self.team.pk,
            distinct_id="distinct_id",
            person_id=shared_uuid,
            is_deleted=True,
            version=107,
        )

        # Phase 2: New event reuses the distinct_id, creating a new person in PG
        # with the same deterministic UUID. The signal writes to CH with version=0,
        # which is ignored because 0 < 105.
        person = create_person(team=self.team, properties={"abcdefg": 11112}, version=0, uuid=shared_uuid)
        add_distinct_id(person=person, distinct_id="distinct_id", version=0)

        # Phase 3: Reset
        response = self.client.post(
            f"/api/projects/{self.team.pk}/persons/reset_person_distinct_id/",
            {"distinct_id": "distinct_id"},
        )
        assert response.status_code == status.HTTP_202_ACCEPTED

        # Verify: personhog distinct_id version was bumped
        resolved = get_person_by_distinct_id(self.team.pk, "distinct_id")
        assert resolved is not None

        # Verify: CH distinct_id is reset
        ch_pdi = sync_execute(
            f"""
            SELECT person_id, version, is_deleted
            FROM {PERSON_DISTINCT_ID2_TABLE} FINAL
            WHERE team_id = %(team_id)s AND distinct_id = 'distinct_id'
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(len(ch_pdi), 1)
        self.assertEqual(ch_pdi[0][2], 0)  # is_deleted
        assert ch_pdi[0][1] > 107  # version beats deletion

        # Verify: CH person is also reset
        ch_person = sync_execute(
            """
            SELECT argMax(is_deleted, version), max(version)
            FROM person FINAL
            WHERE team_id = %(team_id)s AND id = %(person_id)s
            """,
            {"team_id": self.team.pk, "person_id": shared_uuid},
        )
        self.assertEqual(len(ch_person), 1)
        self.assertEqual(ch_person[0][0], 0)  # is_deleted
        assert ch_person[0][1] > 105  # version beats deletion

        # Verify: personhog person version was bumped so future plugin-server updates aren't ignored
        person_after = get_person_by_uuid(self.team.pk, shared_uuid)
        assert person_after is not None
        assert person_after.version is not None and person_after.version > 105

    @mock.patch(
        f"{posthog.models.person.deletion.__name__}.create_person_distinct_id",
        wraps=posthog.models.person.deletion.create_person_distinct_id,
    )
    @pytest.mark.flaky(reruns=2)
    def test_reset_person_distinct_id_not_found(self, mocked_ch_call):
        # person who shouldn't be changed
        person_not_changed_1 = create_person(team=self.team, properties={"abcdef": 1111}, version=0, uuid=uuid4())

        # distinct id no update
        add_distinct_id(person=person_not_changed_1, distinct_id="distinct_id-1", version=0)

        # deleted person not re-used
        person_deleted_1 = create_person(team=self.team, properties={"abcdef": 1111}, version=0, uuid=uuid4())
        add_distinct_id(person=person_deleted_1, distinct_id="distinct_id-del-1", version=16)
        delete_person(person_deleted_1)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/persons/reset_person_distinct_id/",
            {
                "distinct_id": "distinct_id",
            },
        )

        assert response.status_code == status.HTTP_202_ACCEPTED

        # personhog: only the non-deleted distinct_id still resolves to its person
        assert get_person_by_distinct_id(self.team.pk, "distinct_id-del-1") is None
        resolved = get_person_by_distinct_id(self.team.pk, "distinct_id-1")
        assert resolved is not None
        assert resolved.uuid == person_not_changed_1.uuid

        # clickhouse
        ch_person_distinct_ids = sync_execute(
            f"""
            SELECT person_id, team_id, distinct_id, version, is_deleted FROM {PERSON_DISTINCT_ID2_TABLE} FINAL WHERE team_id = %(team_id)s ORDER BY version
            """,
            {"team_id": self.team.pk},
        )
        self.assertEqual(
            ch_person_distinct_ids,
            [
                (person_not_changed_1.uuid, self.team.pk, "distinct_id-1", 0, False),
                (person_deleted_1.uuid, self.team.pk, "distinct_id-del-1", 116, True),
            ],
        )
        mocked_ch_call.assert_not_called()

    def test_batch_by_distinct_ids_happy_path(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["user_1"],
            properties={"email": "user1@example.com"},
            immediate=True,
        )
        _create_person(
            team=self.team,
            distinct_ids=["user_2"],
            properties={"email": "user2@example.com"},
            immediate=True,
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["user_1", "user_2"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertIn("user_1", results)
        self.assertIn("user_2", results)
        self.assertEqual(results["user_1"]["properties"]["email"], "user1@example.com")
        self.assertEqual(results["user_2"]["properties"]["email"], "user2@example.com")

    def test_batch_by_distinct_ids_caps_distinct_ids_at_ten(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=[f"id_{i}" for i in range(12)],
            properties={"email": "many@example.com"},
            immediate=True,
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["id_0"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertIn("id_0", results)
        self.assertLessEqual(len(results["id_0"]["distinct_ids"]), 10)

    def test_batch_by_distinct_ids_missing_ids(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["existing_user"],
            properties={"email": "exists@example.com"},
            immediate=True,
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["existing_user", "nonexistent_1", "nonexistent_2"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertIn("existing_user", results)
        self.assertNotIn("nonexistent_1", results)
        self.assertNotIn("nonexistent_2", results)

    def test_batch_by_distinct_ids_same_person_multiple_ids(self) -> None:
        _create_person(
            team=self.team,
            distinct_ids=["id_a", "id_b"],
            properties={"email": "multi@example.com"},
            immediate=True,
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["id_a", "id_b"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertIn("id_a", results)
        self.assertIn("id_b", results)
        self.assertEqual(results["id_a"]["uuid"], results["id_b"]["uuid"])

    def test_batch_by_distinct_ids_empty_list(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], {})

    def test_batch_by_distinct_ids_invalid_input(self) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": "not_a_list"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], {})

    def test_batch_by_distinct_ids_cross_team_isolation(self) -> None:
        other_org, _, _ = Organization.objects.bootstrap(None, name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        _create_person(
            team=other_team,
            distinct_ids=["other_team_user"],
            properties={"email": "other@example.com"},
            immediate=True,
        )
        _create_person(
            team=self.team,
            distinct_ids=["my_team_user"],
            properties={"email": "mine@example.com"},
            immediate=True,
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": ["my_team_user", "other_team_user"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertIn("my_team_user", results)
        self.assertNotIn("other_team_user", results)

    def test_batch_by_distinct_ids_truncates_at_max_batch_size(self) -> None:
        distinct_ids = [f"user_{i}" for i in range(201)]

        _create_person(
            team=self.team,
            distinct_ids=[distinct_ids[200]],
            properties={"email": "last@example.com"},
            immediate=True,
        )
        flush_persons_and_events()

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/batch_by_distinct_ids/",
            {"distinct_ids": distinct_ids},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertNotIn(distinct_ids[200], results)


class TestPersonFromClickhouse(TestPerson):
    @override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_pagination_limit(self):
        created_ids = []

        for index in range(0, 19):
            created_ids.append(str(index + 100))
            create_person(  # creating without _create_person to guarantee created_at ordering
                team=self.team,
                distinct_ids=[str(index + 100)],
                properties={"$browser": "whatever", "$os": "Windows"},
            )
        returned_ids = []
        response = self.client.get("/api/person/?limit=10").json()
        self.assertEqual(len(response["results"]), 10)
        returned_ids += [x["distinct_ids"][0] for x in response["results"]]
        response_next = self.client.get(response["next"]).json()
        returned_ids += [x["distinct_ids"][0] for x in response_next["results"]]
        self.assertEqual(len(response_next["results"]), 9)

        created_ids.reverse()  # ids are returned in desc order
        self.assertEqual(returned_ids, created_ids, returned_ids)

        response_include_total = self.client.get("/api/person/?limit=10&include_total").json()
        self.assertEqual(response_include_total["count"], 19)  #  With `include_total`, the total count is returned too


class TestPersonBatchRestrictedProperties(ClickhouseTestMixin, APIBaseTest):
    # Regression: batch_by_distinct_ids / batch_by_uuids built MinimalPersonSerializer with a bare
    # {"get_team": ...} context, skipping get_serializer_context() — so restricted_person_properties
    # was never injected and field-level access control was bypassed. The single-person GET path
    # strips restricted properties; the batch paths must too.
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        restricted = PropertyDefinition.objects.create(
            team=self.team, name="ssn", property_type="String", type=PropertyDefinition.Type.PERSON
        )
        # A default rule (no member/role) restricts the property for the default test user, a plain MEMBER.
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=restricted, access_level=PropertyAccessLevel.NONE.value
        )

    @parameterized.expand(["batch_by_distinct_ids", "batch_by_uuids"])
    def test_batch_endpoint_strips_restricted_person_properties(self, action: str) -> None:
        person = _create_person(
            team=self.team,
            distinct_ids=["restricted_user"],
            properties={"email": "visible@example.com", "ssn": "123-45-6789"},
            immediate=True,
        )
        flush_persons_and_events()

        if action == "batch_by_distinct_ids":
            body: dict[str, list[str]] = {"distinct_ids": ["restricted_user"]}
            result_key = "restricted_user"
        else:
            body = {"uuids": [str(person.uuid)]}
            result_key = str(person.uuid)

        response = self.client.post(
            f"/api/environments/{self.team.id}/persons/{action}/",
            body,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        properties = response.json()["results"][result_key]["properties"]
        self.assertEqual(properties.get("email"), "visible@example.com")
        self.assertNotIn("ssn", properties)
