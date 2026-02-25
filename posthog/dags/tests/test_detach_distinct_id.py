import uuid as uuid_module
from uuid import UUID

import pytest
from unittest.mock import MagicMock, patch

from posthog.dags.detach_distinct_id import (
    _count_other_distinct_ids,
    _delete_distinct_id_row,
    _insert_ch_override,
    _lookup_distinct_id,
    _publish_deletion_to_kafka,
    detach_distinct_id_job,
)
from posthog.kafka_client.topics import KAFKA_PERSON_DISTINCT_ID

PERSON_UUID = "5e00024e-cb68-59f6-821f-6150fcffc431"
PERSON_PK = 42
PDI_ID = 99
PDI_VERSION = 3
TEAM_ID = 7
DUMMY_OVERRIDE_UUID = "00000000-0000-0000-0000-000000000001"


def _make_cursor(fetchone_values: list | None = None) -> MagicMock:
    cursor = MagicMock()
    if fetchone_values is not None:
        cursor.fetchone.side_effect = fetchone_values
    return cursor


class TestLookupDistinctId:
    def test_returns_row_when_found_tuple(self):
        cursor = _make_cursor(fetchone_values=[(PDI_ID, PDI_VERSION, PERSON_PK, UUID(PERSON_UUID))])

        result = _lookup_distinct_id(cursor, TEAM_ID, "$posthog_cookieless")

        assert result is not None
        assert result["pdi_id"] == PDI_ID
        assert result["version"] == PDI_VERSION
        assert result["person_pk"] == PERSON_PK
        assert result["person_uuid"] == PERSON_UUID

    def test_returns_row_when_found_dict(self):
        cursor = _make_cursor(
            fetchone_values=[{"id": PDI_ID, "version": PDI_VERSION, "person_id": PERSON_PK, "uuid": UUID(PERSON_UUID)}]
        )

        result = _lookup_distinct_id(cursor, TEAM_ID, "$posthog_cookieless")

        assert result is not None
        assert result["pdi_id"] == PDI_ID
        assert result["version"] == PDI_VERSION
        assert result["person_pk"] == PERSON_PK
        assert result["person_uuid"] == PERSON_UUID

    def test_returns_none_when_not_found(self):
        cursor = _make_cursor(fetchone_values=[None])

        result = _lookup_distinct_id(cursor, TEAM_ID, "nonexistent")

        assert result is None


class TestCountOtherDistinctIds:
    def test_returns_count_tuple(self):
        cursor = _make_cursor(fetchone_values=[(5,)])

        count = _count_other_distinct_ids(cursor, TEAM_ID, PERSON_PK, PDI_ID)

        assert count == 5

    def test_returns_count_dict(self):
        cursor = _make_cursor(fetchone_values=[{"count": 5}])

        count = _count_other_distinct_ids(cursor, TEAM_ID, PERSON_PK, PDI_ID)

        assert count == 5

    def test_returns_zero_when_none(self):
        cursor = _make_cursor(fetchone_values=[(0,)])

        count = _count_other_distinct_ids(cursor, TEAM_ID, PERSON_PK, PDI_ID)

        assert count == 0


class TestDeleteDistinctIdRow:
    def test_locks_and_deletes_tuple(self):
        cursor = _make_cursor(fetchone_values=[(PDI_VERSION,)])

        version = _delete_distinct_id_row(cursor, PDI_ID)

        assert version == PDI_VERSION
        assert cursor.execute.call_count == 2
        assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]
        assert "DELETE" in cursor.execute.call_args_list[1].args[0]

    def test_locks_and_deletes_dict(self):
        cursor = _make_cursor(fetchone_values=[{"version": PDI_VERSION}])

        version = _delete_distinct_id_row(cursor, PDI_ID)

        assert version == PDI_VERSION
        assert cursor.execute.call_count == 2
        assert "FOR UPDATE" in cursor.execute.call_args_list[0].args[0]
        assert "DELETE" in cursor.execute.call_args_list[1].args[0]

    def test_raises_if_row_disappears(self):
        cursor = _make_cursor(fetchone_values=[None])

        with pytest.raises(RuntimeError, match="disappeared"):
            _delete_distinct_id_row(cursor, PDI_ID)


class TestPublishDeletionToKafka:
    def test_publishes_with_version_plus_100(self):
        producer = MagicMock()

        _publish_deletion_to_kafka(producer, TEAM_ID, "$posthog_cookieless", PERSON_UUID, PDI_VERSION)

        producer.produce.assert_called_once_with(
            topic=KAFKA_PERSON_DISTINCT_ID,
            data={
                "distinct_id": "$posthog_cookieless",
                "person_id": PERSON_UUID,
                "team_id": TEAM_ID,
                "version": PDI_VERSION + 100,
                "is_deleted": 1,
            },
        )
        producer.flush.assert_called_once()


class TestInsertChOverride:
    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_inserts_override_row(self, mock_sync_execute):
        _insert_ch_override(TEAM_ID, "$posthog_cookieless", DUMMY_OVERRIDE_UUID, PDI_VERSION + 100)

        mock_sync_execute.assert_called_once()
        sql = mock_sync_execute.call_args.args[0]
        assert "person_distinct_id_overrides" in sql

        rows = mock_sync_execute.call_args.args[1]
        assert len(rows) == 1
        row = rows[0]
        assert row[0] == TEAM_ID
        assert row[1] == "$posthog_cookieless"
        assert row[2] == DUMMY_OVERRIDE_UUID
        assert row[3] == 0  # is_deleted
        assert row[4] == PDI_VERSION + 100  # version


class TestDetachDistinctIdJob:
    """Run the full Dagster job with mock Postgres (psycopg2), Kafka, and ClickHouse
    (sync_execute). Verifies the three cleanup phases only fire when all safety checks pass."""

    def _make_connection(self, lookup_row, other_count, delete_version=PDI_VERSION):
        """Build a mock psycopg2 connection with a cursor that responds to the
        queries issued by detach_distinct_id_op in order."""
        conn = MagicMock(spec=["cursor", "commit", "rollback"])
        cursor = MagicMock()

        # The op issues fetchone calls in this order:
        # 1. _lookup_distinct_id
        # 2. _count_other_distinct_ids
        # 3. _delete_distinct_id_row SELECT FOR UPDATE (only when not dry_run)
        fetchone_sequence = [lookup_row, (other_count,)]
        if delete_version is not None:
            fetchone_sequence.append((delete_version,))

        cursor.fetchone.side_effect = fetchone_sequence
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        return conn, cursor

    def _run_config(self, *, dry_run: bool = True, override_person_id: str | None = None) -> dict:
        config: dict = {
            "team_id": TEAM_ID,
            "distinct_id": "$posthog_cookieless",
            "expected_person_id": PERSON_UUID,
            "dry_run": dry_run,
        }
        if override_person_id is not None:
            config["override_person_id"] = override_person_id
        return {"ops": {"detach_distinct_id_op": {"config": config}}}

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_dry_run_does_not_mutate(self, mock_sync_execute):
        lookup_row = (PDI_ID, PDI_VERSION, PERSON_PK, UUID(PERSON_UUID))
        conn, cursor = self._make_connection(lookup_row, other_count=2)
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(dry_run=True),
            resources={"persons_database": conn, "kafka_producer": producer},
        )

        assert result.success
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    @patch("posthog.dags.detach_distinct_id.uuid.uuid4", return_value=UUID(DUMMY_OVERRIDE_UUID))
    def test_detaches_publishes_kafka_and_inserts_override(self, _mock_uuid4, mock_sync_execute):
        lookup_row = (PDI_ID, PDI_VERSION, PERSON_PK, UUID(PERSON_UUID))
        conn, cursor = self._make_connection(lookup_row, other_count=2)
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(dry_run=False),
            resources={"persons_database": conn, "kafka_producer": producer},
        )

        assert result.success
        conn.commit.assert_called_once()

        # Kafka deletion
        producer.produce.assert_called_once()
        kafka_data = producer.produce.call_args.kwargs["data"]
        assert kafka_data["distinct_id"] == "$posthog_cookieless"
        assert kafka_data["person_id"] == PERSON_UUID
        assert kafka_data["is_deleted"] == 1
        assert kafka_data["version"] == PDI_VERSION + 100
        producer.flush.assert_called_once()

        # ClickHouse override
        mock_sync_execute.assert_called_once()
        override_rows = mock_sync_execute.call_args.args[1]
        assert override_rows[0][0] == TEAM_ID
        assert override_rows[0][1] == "$posthog_cookieless"
        assert override_rows[0][2] == DUMMY_OVERRIDE_UUID
        assert override_rows[0][4] == PDI_VERSION + 100

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_uses_explicit_override_person_id(self, mock_sync_execute):
        explicit_uuid = "11111111-2222-3333-4444-555555555555"
        lookup_row = (PDI_ID, PDI_VERSION, PERSON_PK, UUID(PERSON_UUID))
        conn, cursor = self._make_connection(lookup_row, other_count=2)
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(dry_run=False, override_person_id=explicit_uuid),
            resources={"persons_database": conn, "kafka_producer": producer},
        )

        assert result.success
        mock_sync_execute.assert_called_once()
        override_rows = mock_sync_execute.call_args.args[1]
        assert override_rows[0][2] == explicit_uuid

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_fails_when_distinct_id_not_found(self, mock_sync_execute):
        conn, cursor = self._make_connection(lookup_row=None, other_count=0, delete_version=None)
        cursor.fetchone.side_effect = [None]
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(dry_run=False),
            resources={"persons_database": conn, "kafka_producer": producer},
            raise_on_error=False,
        )

        assert not result.success
        conn.commit.assert_not_called()
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_fails_when_person_id_mismatch(self, mock_sync_execute):
        wrong_person = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        lookup_row = (PDI_ID, PDI_VERSION, PERSON_PK, wrong_person)
        conn, cursor = self._make_connection(lookup_row, other_count=2)
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(dry_run=False),
            resources={"persons_database": conn, "kafka_producer": producer},
            raise_on_error=False,
        )

        assert not result.success
        conn.commit.assert_not_called()
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_fails_when_only_distinct_id(self, mock_sync_execute):
        lookup_row = (PDI_ID, PDI_VERSION, PERSON_PK, UUID(PERSON_UUID))
        conn, cursor = self._make_connection(lookup_row, other_count=0)
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(dry_run=False),
            resources={"persons_database": conn, "kafka_producer": producer},
            raise_on_error=False,
        )

        assert not result.success
        conn.commit.assert_not_called()
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestDetachDistinctIdIntegration:
    """Integration tests using a real Django Postgres connection.

    Exercises the full Dagster job against real DB rows so cursor return types
    (tuple vs dict) are tested against production-like conditions.
    Kafka and ClickHouse (sync_execute) remain mocked.
    """

    @pytest.fixture
    def organization(self):
        from posthog.models import Organization

        return Organization.objects.create(name="Detach Test Org")

    @pytest.fixture
    def team(self, organization):
        from posthog.models import Team

        return Team.objects.create(organization=organization, name="Detach Test Team")

    @pytest.fixture
    def person_with_two_distinct_ids(self, team):
        from posthog.models.person import Person, PersonDistinctId

        person = Person.objects.create(team_id=team.id, version=1)
        pdi_keep = PersonDistinctId.objects.create(team=team, person=person, distinct_id="keep_this", version=0)
        pdi_detach = PersonDistinctId.objects.create(
            team=team, person=person, distinct_id="$posthog_cookieless", version=3
        )
        return person, pdi_keep, pdi_detach

    @staticmethod
    def _run_config(team_id: int, person_uuid: str, *, dry_run: bool, distinct_id: str = "$posthog_cookieless") -> dict:
        return {
            "ops": {
                "detach_distinct_id_op": {
                    "config": {
                        "team_id": team_id,
                        "distinct_id": distinct_id,
                        "expected_person_id": person_uuid,
                        "dry_run": dry_run,
                    }
                }
            }
        }

    @staticmethod
    def _get_persons_conn():
        from django.db import connections

        from posthog.person_db_router import PERSONS_DB_FOR_WRITE

        return connections[PERSONS_DB_FOR_WRITE]

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_dry_run_does_not_delete(self, mock_sync_execute, team, person_with_two_distinct_ids):
        from posthog.models.person import PersonDistinctId

        person, _pdi_keep, pdi_detach = person_with_two_distinct_ids
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(team.id, str(person.uuid), dry_run=True),
            resources={"persons_database": self._get_persons_conn(), "kafka_producer": producer},
        )

        assert result.success
        assert PersonDistinctId.objects.filter(id=pdi_detach.id).exists()
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_live_run_deletes_and_publishes(self, mock_sync_execute, team, person_with_two_distinct_ids):
        from posthog.models.person import PersonDistinctId

        person, pdi_keep, pdi_detach = person_with_two_distinct_ids
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(team.id, str(person.uuid), dry_run=False),
            resources={"persons_database": self._get_persons_conn(), "kafka_producer": producer},
        )

        assert result.success

        # PDI row deleted
        assert not PersonDistinctId.objects.filter(id=pdi_detach.id).exists()
        # Other PDI untouched
        assert PersonDistinctId.objects.filter(id=pdi_keep.id).exists()

        # Kafka deletion published
        producer.produce.assert_called_once()
        kafka_data = producer.produce.call_args.kwargs["data"]
        assert kafka_data["distinct_id"] == "$posthog_cookieless"
        assert kafka_data["person_id"] == str(person.uuid)
        assert kafka_data["team_id"] == team.id
        assert kafka_data["is_deleted"] == 1
        assert kafka_data["version"] == pdi_detach.version + 100

        # ClickHouse override inserted
        mock_sync_execute.assert_called_once()
        override_rows = mock_sync_execute.call_args.args[1]
        assert override_rows[0][0] == team.id
        assert override_rows[0][1] == "$posthog_cookieless"

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_fails_on_person_id_mismatch(self, mock_sync_execute, team, person_with_two_distinct_ids):
        person, _, _ = person_with_two_distinct_ids
        wrong_uuid = str(uuid_module.uuid4())
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(team.id, wrong_uuid, dry_run=False),
            resources={"persons_database": self._get_persons_conn(), "kafka_producer": producer},
            raise_on_error=False,
        )

        assert not result.success
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_fails_when_only_distinct_id(self, mock_sync_execute, team):
        from posthog.models.person import Person, PersonDistinctId

        person = Person.objects.create(team_id=team.id, version=1)
        PersonDistinctId.objects.create(team=team, person=person, distinct_id="$posthog_cookieless", version=3)
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(team.id, str(person.uuid), dry_run=False),
            resources={"persons_database": self._get_persons_conn(), "kafka_producer": producer},
            raise_on_error=False,
        )

        assert not result.success
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()

    @patch("posthog.dags.detach_distinct_id.sync_execute")
    def test_fails_when_distinct_id_not_found(self, mock_sync_execute, team):
        producer = MagicMock()

        result = detach_distinct_id_job.execute_in_process(
            run_config=self._run_config(team.id, str(uuid_module.uuid4()), dry_run=False, distinct_id="nonexistent"),
            resources={"persons_database": self._get_persons_conn(), "kafka_producer": producer},
            raise_on_error=False,
        )

        assert not result.success
        producer.produce.assert_not_called()
        mock_sync_execute.assert_not_called()
