import json
from typing import Any

import pytest
from pydantic import BaseModel

from posthog.hogql.errors import HogQLException
from posthog.models.utils import UUIDT
from posthog.queries.insight import insight_sync_execute
from django.test import override_settings
from freezegun import freeze_time
from posthog.hogql.context import HogQLContext
from posthog.hogql.database import (
    Table,
    StringDatabaseField,
    IntegerDatabaseField,
    StringJSONDatabaseField,
    SQLExprField,
    create_hogql_database,
    serialize_database,
)
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast

from posthog.test.base import BaseTest, _create_person, flush_persons_and_events, _create_event


class TestDatabase(BaseTest):
    snapshot: Any

    def _create_random_events(self) -> str:
        random_uuid = str(UUIDT())
        _create_person(
            properties={"sneaky_mail": "tim@posthog.com", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        flush_persons_and_events()
        for index in range(2):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"$browser": "Chrome", "$browser_version": "92", "random_uuid": random_uuid, "index": index},
            )
        flush_persons_and_events()
        return random_uuid

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_no_person_on_events(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=False):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    @pytest.mark.usefixtures("unittest_snapshot")
    def test_serialize_database_with_person_on_events_enabled(self):
        with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
            serialized_database = serialize_database(create_hogql_database(team_id=self.team.pk))
            assert json.dumps(serialized_database, indent=4) == self.snapshot

    def test_sql_expr_fields(self):
        from posthog.hogql import ast

        class EventsTable(Table):
            event: StringDatabaseField = StringDatabaseField(name="event")
            team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
            properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
            custom_field_1: BaseModel = SQLExprField(sql="'hello world'")
            custom_field_2: BaseModel = SQLExprField(expr=ast.Call(name="upper", args=[ast.Field(chain=["event"])]))
            custom_field_3: BaseModel = SQLExprField(sql="1 + 2")
            custom_field_4: BaseModel = SQLExprField(
                sql="concat(properties.$browser, ' ', properties.$browser_version)"
            )

            def clickhouse_table(self):
                return "events"

            def hogql_table(self):
                return "events"

        with freeze_time("2020-01-10"):
            self._create_random_events()
            database = create_hogql_database(self.team.pk)
            database.events = EventsTable()
            clickhouse_context = HogQLContext(
                database=database,
                team_id=self.team.pk,
                enable_select_queries=True,
            )
            query = parse_select(
                "select event, custom_field_1, custom_field_2, custom_field_3, custom_field_4 from events order by custom_field_2 limit 1"
            )
            clickhouse_sql = print_ast(query, context=clickhouse_context, dialect="clickhouse")
            results, types = insight_sync_execute(
                clickhouse_sql,
                clickhouse_context.values,
                with_column_types=True,
                query_type="hogql_query",
            )
            self.assertEqual(
                results,
                [
                    ("random event", "hello world", "RANDOM EVENT", 3, "Chrome 92"),
                ],
            )
            self.assertEqual(
                clickhouse_sql,
                f"SELECT events.event, %(hogql_val_0)s AS custom_field_1, upper(events.event) AS custom_field_2, "
                f"plus(1, 2) AS custom_field_3, concat(events.`mat_$browser`, %(hogql_val_1)s, "
                f"replaceRegexpAll(JSONExtractRaw(events.properties, %(hogql_val_2)s), '^\"|\"$', '')) AS custom_field_4 "
                f"FROM events WHERE equals(events.team_id, {self.team.pk}) "
                f"ORDER BY upper(events.event) AS custom_field_2 ASC "
                f"LIMIT 1",
            )

    def test_sql_expr_broken_field(self):
        class EventsTable(Table):
            event: StringDatabaseField = StringDatabaseField(name="event")
            team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
            properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
            custom_field_2: BaseModel = SQLExprField(sql="upper(eve")

            def clickhouse_table(self):
                return "events"

            def hogql_table(self):
                return "events"

        with freeze_time("2020-01-10"):
            self._create_random_events()
            database = create_hogql_database(self.team.pk)
            database.events = EventsTable()
            clickhouse_context = HogQLContext(
                database=database,
                team_id=self.team.pk,
                enable_select_queries=True,
            )

            with self.assertRaises(HogQLException) as e:
                query = parse_select("select event, custom_field_2 from events order by custom_field_2 limit 1")
                print_ast(query, context=clickhouse_context, dialect="clickhouse")

            self.assertEqual(
                str(e.exception),
                "Error parsing SQL field \"upper(eve\": Syntax error at line 1, column 9: no viable alternative at input 'upper(eve'",
            )
