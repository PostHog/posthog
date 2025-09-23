import json
from io import BytesIO

from posthog.test.base import BaseTest

import fastavro

from posthog.models import DataWarehouseTable
from posthog.warehouse.models import DataWarehouseCredential

from ee.hogai.eval.schema import DataWarehouseTableSnapshot


class TestEvalSchema(BaseTest):
    def setUp(self):
        super().setUp()
        self.credential = DataWarehouseCredential.objects.create(
            access_key="test_key",
            access_secret="test_secret",
            team=self.team,
        )

    def test_serialize_deserialize_for_team(self):
        columns = {
            "id": {"hogql": "IntegerDatabaseField", "valid": True, "clickhouse": "Int64"},
        }
        # Create test data warehouse tables
        DataWarehouseTable.objects.create(
            name="users_table",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="http://example.com/users.parquet",
            columns=columns,
        )

        DataWarehouseTable.objects.create(
            name="events_table",
            format="CSV",
            team=self.team,
            credential=self.credential,
            url_pattern="http://example.com/events.csv",
            columns=columns,
        )

        # Test serialization
        snapshots = list(DataWarehouseTableSnapshot.serialize_for_team(team_id=self.team.id))

        self.assertEqual(len(snapshots), 2)

        # Test first table snapshot
        self.assertEqual(snapshots[0].name, "users_table")
        self.assertEqual(snapshots[0].format, "Parquet")
        self.assertTrue(isinstance(snapshots[0].columns, str))
        self.assertEqual(json.loads(snapshots[0].columns), columns)

        # Test second table snapshot
        self.assertEqual(snapshots[1].name, "events_table")
        self.assertEqual(snapshots[1].format, "CSV")
        self.assertTrue(isinstance(snapshots[1].columns, str))
        self.assertEqual(json.loads(snapshots[1].columns), columns)

        deserialized_snapshots = list(
            DataWarehouseTableSnapshot.deserialize_for_team(snapshots, team_id=self.team.id, project_id=self.project.id)
        )

        self.assertEqual(len(deserialized_snapshots), 2)

        self.assertEqual(deserialized_snapshots[0].name, "users_table")
        self.assertEqual(deserialized_snapshots[0].format, "Parquet")
        self.assertEqual(deserialized_snapshots[0].columns, columns)

        self.assertEqual(deserialized_snapshots[1].name, "events_table")
        self.assertEqual(deserialized_snapshots[1].format, "CSV")
        self.assertEqual(deserialized_snapshots[1].columns, columns)

    def test_serialize_deserialize_for_team_empty_columns(self):
        # Create test data warehouse tables
        DataWarehouseTable.objects.create(
            name="users_table",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="http://example.com/users.parquet",
            columns=None,
        )

        snapshots = list(DataWarehouseTableSnapshot.serialize_for_team(team_id=self.team.id))

        self.assertEqual(len(snapshots), 1)

        self.assertEqual(snapshots[0].name, "users_table")
        self.assertEqual(snapshots[0].format, "Parquet")
        self.assertEqual(snapshots[0].columns, "")

        deserialized_snapshots = list(
            DataWarehouseTableSnapshot.deserialize_for_team(snapshots, team_id=self.team.id, project_id=self.project.id)
        )

        self.assertEqual(len(deserialized_snapshots), 1)

        self.assertEqual(deserialized_snapshots[0].name, "users_table")
        self.assertEqual(deserialized_snapshots[0].format, "Parquet")
        self.assertEqual(deserialized_snapshots[0].columns, {})

    def test_fastavro_serialization(self):
        """Test that a serialized DataWarehouseTableSnapshot can be dumped with fastavro"""
        columns = {
            "id": {"hogql": "IntegerDatabaseField", "valid": True, "clickhouse": "Int64"},
        }

        # Create test data warehouse table
        DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="http://example.com/test.parquet",
            columns=columns,
        )

        # Serialize to snapshot
        snapshots = list(DataWarehouseTableSnapshot.serialize_for_team(team_id=self.team.id))
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]

        # Get the Avro schema from the snapshot
        avro_schema = snapshot.avro_schema()

        # Test that we can serialize the snapshot to Avro using fastavro
        buffer = BytesIO()

        # Convert snapshot to dict for fastavro
        snapshot_dict = snapshot.model_dump()

        # Write to Avro format
        fastavro.writer(buffer, avro_schema, [snapshot_dict])

        # Verify we can read it back
        buffer.seek(0)
        reader = fastavro.reader(buffer)

        # Read back the data
        records = list(
            DataWarehouseTableSnapshot.deserialize_for_team(
                [DataWarehouseTableSnapshot.model_validate(record) for record in reader],
                team_id=self.team.id,
                project_id=self.project.id,
            )
        )
        self.assertEqual(len(records), 1)

        record = records[0]
        self.assertEqual(record.name, "test_table")
        self.assertEqual(record.format, "Parquet")
        self.assertEqual(record.columns, columns)

    def test_fastavro_serialization_empty_columns(self):
        """Test that a serialized DataWarehouseTableSnapshot can be dumped with fastavro"""
        # Create test data warehouse table
        DataWarehouseTable.objects.create(
            name="test_table",
            format="Parquet",
            team=self.team,
            credential=self.credential,
            url_pattern="http://example.com/test.parquet",
            columns=None,
        )

        # Serialize to snapshot
        snapshots = list(DataWarehouseTableSnapshot.serialize_for_team(team_id=self.team.id))
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]

        # Get the Avro schema from the snapshot
        avro_schema = snapshot.avro_schema()

        # Test that we can serialize the snapshot to Avro using fastavro
        buffer = BytesIO()

        # Convert snapshot to dict for fastavro
        snapshot_dict = snapshot.model_dump()

        # Write to Avro format
        fastavro.writer(buffer, avro_schema, [snapshot_dict])

        # Verify we can read it back
        buffer.seek(0)
        reader = fastavro.reader(buffer)

        # Read back the data
        records = list(
            DataWarehouseTableSnapshot.deserialize_for_team(
                [DataWarehouseTableSnapshot.model_validate(record) for record in reader],
                team_id=self.team.id,
                project_id=self.project.id,
            )
        )
        self.assertEqual(len(records), 1)

        record = records[0]
        self.assertEqual(record.name, "test_table")
        self.assertEqual(record.format, "Parquet")
        self.assertEqual(record.columns, {})
