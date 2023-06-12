import json
from typing import Any

import pytest
from django.test import override_settings

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

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_database_with_warehouse_tables(self):
        credential = DataWarehouseCredential.objects.create(
            team=self.team, access_key="_accesskey", access_secret="_secret"
        )
        DataWarehouseTable.objects.create(
            name="whatever", team=self.team, columns={"id": "String"}, credential=credential
        )
        create_hogql_database(team_id=self.team.pk)

        response = execute_hogql_query(
            "select * from whatever",
            team=self.team,
        )
        self.assertEqual(
            response.clickhouse,
            f"SELECT event FROM events WHERE and(equals(events.team_id, {self.team.id}), equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY events.event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
        )
