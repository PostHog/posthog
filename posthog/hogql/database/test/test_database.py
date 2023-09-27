import json
from typing import Any

from unittest.mock import patch
import pytest
from django.test import override_settings
from parameterized import parameterized

from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.test.base import BaseTest
from posthog.warehouse.models import DataWarehouseTable, DataWarehouseCredential
from posthog.hogql.query import execute_hogql_query


class TestDatabase(BaseTest):
    snapshot: Any

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_no_person_on_events(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_with_person_on_events_enabled(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @parameterized.expand([False, True])
    def test_can_select_from_each_table_at_all(self, poe_enabled: bool) -> None:
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=poe_enabled):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            for table, possible_columns in serialized_database.items():
                if table == "numbers":
                    execute_hogql_query("SELECT number FROM numbers(10) LIMIT 100", self.team)
                else:
                    columns = [
                        x["key"]
                        for x in possible_columns
                        if "table" not in x and "chain" not in x and "fields" not in x
                    ]
                    execute_hogql_query(f"SELECT {','.join(columns)} FROM {table}", team=self.team)

    @patch("posthog.hogql.query.sync_execute", return_value=(None, None))
    @pytest.mark.usefixtures("unittest_snapshot")
    def test_database_with_warehouse_tables(self, patch_execute):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            name="whatever", team=self.team, columns={"id": "String"}, credential=credential, url_pattern=""
        )
        create_hogql_database(team_id=self.team.pk)

        response = execute_hogql_query(
            "select * from whatever",
            team=self.team,
        )

        self.assertEqual(
            response.clickhouse,
            f"SELECT whatever.id FROM s3Cluster('posthog', %(hogql_val_0_sensitive)s, %(hogql_val_3_sensitive)s, %(hogql_val_4_sensitive)s, %(hogql_val_1)s, %(hogql_val_2)s) AS whatever LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
        )
