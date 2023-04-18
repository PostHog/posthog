from datetime import timezone, datetime, date
from uuid import UUID

from freezegun import freeze_time

from posthog.hogql import ast
from posthog.hogql.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_types
from posthog.test.base import BaseTest


class TestResolver(BaseTest):
    def setUp(self):
        self.database = create_hogql_database(self.team.pk)

    def test_resolve_events_table(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        resolve_types(expr, self.database)

        events_table_type = ast.TableType(table=self.database.events)
        event_field_type = ast.FieldType(name="event", table_type=events_table_type)
        timestamp_field_type = ast.FieldType(name="timestamp", table_type=events_table_type)
        select_query_type = ast.SelectQueryType(
            columns={"event": event_field_type, "timestamp": timestamp_field_type},
            tables={"events": events_table_type},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], type=event_field_type),
                ast.Field(chain=["events", "timestamp"], type=timestamp_field_type),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                type=events_table_type,
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["events", "event"], type=event_field_type),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="test", type=ast.ConstantType(data_type="str")),
                type=ast.ConstantType(data_type="bool"),
            ),
            type=select_query_type,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_alias(self):
        expr = parse_select("SELECT event, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_types(expr, database=self.database)

        events_table_type = ast.TableType(table=self.database.events)
        events_table_alias_type = ast.TableAliasType(alias="e", table_type=events_table_type)
        event_field_type = ast.FieldType(name="event", table_type=events_table_alias_type)
        timestamp_field_type = ast.FieldType(name="timestamp", table_type=events_table_alias_type)
        select_query_type = ast.SelectQueryType(
            columns={"event": event_field_type, "timestamp": timestamp_field_type},
            tables={"e": events_table_alias_type},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], type=event_field_type),
                ast.Field(chain=["e", "timestamp"], type=timestamp_field_type),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                alias="e",
                type=events_table_alias_type,
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], type=event_field_type),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="test", type=ast.ConstantType(data_type="str")),
                type=ast.ConstantType(data_type="bool"),
            ),
            type=select_query_type,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias(self):
        expr = parse_select("SELECT event as ee, ee, ee as e, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_types(expr, database=self.database)

        events_table_type = ast.TableType(table=self.database.events)
        events_table_alias_type = ast.TableAliasType(alias="e", table_type=events_table_type)
        event_field_type = ast.FieldType(name="event", table_type=events_table_alias_type)
        timestamp_field_type = ast.FieldType(name="timestamp", table_type=events_table_alias_type)

        select_query_type = ast.SelectQueryType(
            aliases={
                "ee": ast.FieldAliasType(alias="ee", type=event_field_type),
                "e": ast.FieldAliasType(alias="e", type=ast.FieldAliasType(alias="ee", type=event_field_type)),
            },
            columns={
                "ee": ast.FieldAliasType(alias="ee", type=event_field_type),
                "e": ast.FieldAliasType(alias="e", type=ast.FieldAliasType(alias="ee", type=event_field_type)),
                "timestamp": timestamp_field_type,
            },
            tables={"e": events_table_alias_type},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="ee",
                    expr=ast.Field(chain=["event"], type=event_field_type),
                    type=select_query_type.aliases["ee"],
                ),
                ast.Field(chain=["ee"], type=select_query_type.aliases["ee"]),
                ast.Alias(
                    alias="e",
                    expr=ast.Field(chain=["ee"], type=select_query_type.aliases["ee"]),
                    type=select_query_type.aliases["e"],  # is ee ?
                ),
                ast.Field(chain=["e", "timestamp"], type=timestamp_field_type),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                alias="e",
                type=select_query_type.tables["e"],
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], type=event_field_type),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="test", type=ast.ConstantType(data_type="str")),
                type=ast.ConstantType(data_type="bool"),
            ),
            type=select_query_type,
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias_inside_subquery(self):
        expr = parse_select("SELECT b FROM (select event as b, timestamp as c from events) e WHERE e.b = 'test'")
        resolve_types(expr, database=self.database)
        inner_events_table_type = ast.TableType(table=self.database.events)
        inner_event_field_type = ast.FieldAliasType(
            alias="b", type=ast.FieldType(name="event", table_type=inner_events_table_type)
        )
        timestamp_field_type = ast.FieldType(name="timestamp", table_type=inner_events_table_type)
        timstamp_alias_type = ast.FieldAliasType(alias="c", type=timestamp_field_type)
        inner_select_type = ast.SelectQueryType(
            aliases={
                "b": inner_event_field_type,
                "c": ast.FieldAliasType(alias="c", type=timestamp_field_type),
            },
            columns={
                "b": inner_event_field_type,
                "c": ast.FieldAliasType(alias="c", type=timestamp_field_type),
            },
            tables={
                "events": inner_events_table_type,
            },
        )
        select_alias_type = ast.SelectQueryAliasType(alias="e", select_query_type=inner_select_type)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["b"],
                    type=ast.FieldType(
                        name="b",
                        table_type=ast.SelectQueryAliasType(alias="e", select_query_type=inner_select_type),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="b",
                            expr=ast.Field(chain=["event"], type=inner_event_field_type.type),
                            type=inner_event_field_type,
                        ),
                        ast.Alias(
                            alias="c",
                            expr=ast.Field(chain=["timestamp"], type=timestamp_field_type),
                            type=timstamp_alias_type,
                        ),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"], type=inner_events_table_type),
                        type=inner_events_table_type,
                    ),
                    type=inner_select_type,
                ),
                alias="e",
                type=select_alias_type,
            ),
            where=ast.CompareOperation(
                left=ast.Field(
                    chain=["e", "b"],
                    type=ast.FieldType(name="b", table_type=select_alias_type),
                ),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="test", type=ast.ConstantType(data_type="str")),
                type=ast.ConstantType(data_type="bool"),
            ),
            type=ast.SelectQueryType(
                aliases={},
                columns={"b": ast.FieldType(name="b", table_type=select_alias_type)},
                tables={"e": select_alias_type},
            ),
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_subquery_no_field_access(self):
        # From ClickHouse's GitHub: "Aliases defined outside of subquery are not visible in subqueries (but see below)."
        expr = parse_select(
            "SELECT event, (select count() from events where event = e.event) as c FROM events e where event = '$pageview'"
        )
        with self.assertRaises(ResolverException) as e:
            resolve_types(expr, database=self.database)
        self.assertEqual(str(e.exception), "Unable to resolve field: e")

    def test_resolve_constant_type(self):
        with freeze_time("2020-01-10 00:00:00"):
            expr = parse_select(
                "SELECT 1, 'boo', true, 1.1232, null, {date}, {datetime}, {uuid}, {array}, {tuple}",
                placeholders={
                    "date": ast.Constant(value=date(2020, 1, 10)),
                    "datetime": ast.Constant(value=datetime(2020, 1, 10, 0, 0, 0, tzinfo=timezone.utc)),
                    "uuid": ast.Constant(value=UUID("00000000-0000-4000-8000-000000000000")),
                    "array": ast.Constant(value=[]),
                    "tuple": ast.Constant(value=(1, 2, 3)),
                },
            )
            resolve_types(expr, database=self.database)
            expected = ast.SelectQuery(
                select=[
                    ast.Constant(value=1, type=ast.ConstantType(data_type="int")),
                    ast.Constant(value="boo", type=ast.ConstantType(data_type="str")),
                    ast.Constant(value=True, type=ast.ConstantType(data_type="bool")),
                    ast.Constant(value=1.1232, type=ast.ConstantType(data_type="float")),
                    ast.Constant(value=None, type=ast.ConstantType(data_type="unknown")),
                    ast.Constant(value=date(2020, 1, 10), type=ast.ConstantType(data_type="date")),
                    ast.Constant(
                        value=datetime(2020, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
                        type=ast.ConstantType(data_type="datetime"),
                    ),
                    ast.Constant(
                        value=UUID("00000000-0000-4000-8000-000000000000"), type=ast.ConstantType(data_type="uuid")
                    ),
                    ast.Constant(value=[], type=ast.ConstantType(data_type="array")),
                    ast.Constant(value=(1, 2, 3), type=ast.ConstantType(data_type="tuple")),
                ],
                type=ast.SelectQueryType(aliases={}, columns={}, tables={}),
            )
            self.assertEqual(expr, expected)

    def test_resolve_boolean_operation_types(self):
        expr = parse_select("SELECT 1 and 1, 1 or 1, not true")
        resolve_types(expr, database=self.database)
        expected = ast.SelectQuery(
            select=[
                ast.And(
                    exprs=[
                        ast.Constant(value=1, type=ast.ConstantType(data_type="int")),
                        ast.Constant(value=1, type=ast.ConstantType(data_type="int")),
                    ],
                    type=ast.ConstantType(data_type="bool"),
                ),
                ast.Or(
                    exprs=[
                        ast.Constant(value=1, type=ast.ConstantType(data_type="int")),
                        ast.Constant(value=1, type=ast.ConstantType(data_type="int")),
                    ],
                    type=ast.ConstantType(data_type="bool"),
                ),
                ast.Not(
                    expr=ast.Constant(value=True, type=ast.ConstantType(data_type="bool")),
                    type=ast.ConstantType(data_type="bool"),
                ),
            ],
            type=ast.SelectQueryType(aliases={}, columns={}, tables={}),
        )
        self.assertEqual(expr, expected)

    def test_resolve_errors(self):
        queries = [
            "SELECT event, (select count() from events where event = x.event) as c FROM events x where event = '$pageview'",
            "SELECT x, (SELECT 1 AS x)",
            "SELECT x IN (SELECT 1 AS x)",
            "SELECT events.x FROM (SELECT event as x FROM events) AS t",
            "SELECT x.y FROM (SELECT event as y FROM events AS x) AS t",
        ]
        for query in queries:
            with self.assertRaises(ResolverException) as e:
                resolve_types(parse_select(query), self.database)
            self.assertIn("Unable to resolve field:", str(e.exception))

    def test_resolve_lazy_pdi_person_table(self):
        expr = parse_select("select distinct_id, person.id from person_distinct_ids")
        resolve_types(expr, database=self.database)
        pdi_table_type = ast.TableType(table=self.database.person_distinct_ids)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["distinct_id"],
                    type=ast.FieldType(name="distinct_id", table_type=pdi_table_type),
                ),
                ast.Field(
                    chain=["person", "id"],
                    type=ast.FieldType(
                        name="id",
                        table_type=ast.LazyJoinType(
                            table_type=pdi_table_type,
                            field="person",
                            lazy_join=self.database.person_distinct_ids.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["person_distinct_ids"], type=pdi_table_type),
                type=pdi_table_type,
            ),
            type=ast.SelectQueryType(
                aliases={},
                anonymous_tables=[],
                columns={
                    "distinct_id": ast.FieldType(name="distinct_id", table_type=pdi_table_type),
                    "id": ast.FieldType(
                        name="id",
                        table_type=ast.LazyJoinType(
                            table_type=pdi_table_type,
                            lazy_join=self.database.person_distinct_ids.person,
                            field="person",
                        ),
                    ),
                },
                tables={"person_distinct_ids": pdi_table_type},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table(self):
        expr = parse_select("select event, pdi.person_id from events")
        resolve_types(expr, database=self.database)
        events_table_type = ast.TableType(table=self.database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    type=ast.FieldType(name="event", table_type=events_table_type),
                ),
                ast.Field(
                    chain=["pdi", "person_id"],
                    type=ast.FieldType(
                        name="person_id",
                        table_type=ast.LazyJoinType(
                            table_type=events_table_type, field="pdi", lazy_join=self.database.events.pdi
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                type=events_table_type,
            ),
            type=ast.SelectQueryType(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldType(name="event", table_type=events_table_type),
                    "person_id": ast.FieldType(
                        name="person_id",
                        table_type=ast.LazyJoinType(
                            table_type=events_table_type,
                            lazy_join=self.database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"events": events_table_type},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table_aliased(self):
        expr = parse_select("select event, e.pdi.person_id from events e")
        resolve_types(expr, database=self.database)
        events_table_type = ast.TableType(table=self.database.events)
        events_table_alias_type = ast.TableAliasType(table_type=events_table_type, alias="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    type=ast.FieldType(name="event", table_type=events_table_alias_type),
                ),
                ast.Field(
                    chain=["e", "pdi", "person_id"],
                    type=ast.FieldType(
                        name="person_id",
                        table_type=ast.LazyJoinType(
                            table_type=events_table_alias_type, field="pdi", lazy_join=self.database.events.pdi
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                alias="e",
                type=events_table_alias_type,
            ),
            type=ast.SelectQueryType(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldType(name="event", table_type=events_table_alias_type),
                    "person_id": ast.FieldType(
                        name="person_id",
                        table_type=ast.LazyJoinType(
                            table_type=events_table_alias_type,
                            lazy_join=self.database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"e": events_table_alias_type},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table(self):
        expr = parse_select("select event, pdi.person.id from events")
        resolve_types(expr, database=self.database)
        events_table_type = ast.TableType(table=self.database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    type=ast.FieldType(name="event", table_type=events_table_type),
                ),
                ast.Field(
                    chain=["pdi", "person", "id"],
                    type=ast.FieldType(
                        name="id",
                        table_type=ast.LazyJoinType(
                            table_type=ast.LazyJoinType(
                                table_type=events_table_type, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                type=events_table_type,
            ),
            type=ast.SelectQueryType(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldType(name="event", table_type=events_table_type),
                    "id": ast.FieldType(
                        name="id",
                        table_type=ast.LazyJoinType(
                            table_type=ast.LazyJoinType(
                                table_type=events_table_type, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                },
                tables={"events": events_table_type},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table_aliased(self):
        expr = parse_select("select event, e.pdi.person.id from events e")
        resolve_types(expr, database=self.database)
        events_table_type = ast.TableType(table=self.database.events)
        events_table_alias_type = ast.TableAliasType(table_type=events_table_type, alias="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    type=ast.FieldType(name="event", table_type=events_table_alias_type),
                ),
                ast.Field(
                    chain=["e", "pdi", "person", "id"],
                    type=ast.FieldType(
                        name="id",
                        table_type=ast.LazyJoinType(
                            table_type=ast.LazyJoinType(
                                table_type=events_table_alias_type, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                alias="e",
                type=events_table_alias_type,
            ),
            type=ast.SelectQueryType(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldType(name="event", table_type=events_table_alias_type),
                    "id": ast.FieldType(
                        name="id",
                        table_type=ast.LazyJoinType(
                            table_type=ast.LazyJoinType(
                                table_type=events_table_alias_type, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                },
                tables={"e": events_table_alias_type},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_virtual_events_poe(self):
        expr = parse_select("select event, poe.id from events")
        resolve_types(expr, database=self.database)
        events_table_type = ast.TableType(table=self.database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    type=ast.FieldType(name="event", table_type=events_table_type),
                ),
                ast.Field(
                    chain=["poe", "id"],
                    type=ast.FieldType(
                        name="id",
                        table_type=ast.VirtualTableType(
                            table_type=events_table_type, field="poe", virtual_table=self.database.events.poe
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], type=events_table_type),
                type=events_table_type,
            ),
            type=ast.SelectQueryType(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldType(name="event", table_type=events_table_type),
                    "id": ast.FieldType(
                        name="id",
                        table_type=ast.VirtualTableType(
                            table_type=events_table_type, field="poe", virtual_table=self.database.events.poe
                        ),
                    ),
                },
                tables={"events": events_table_type},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_resolve_union_all(self):
        node = parse_select("select event, timestamp from events union all select event, timestamp from events")
        resolve_types(node, self.database)

        events_table_type = ast.TableType(table=self.database.events)
        self.assertEqual(
            node.select_queries[0].select,
            [
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table_type=events_table_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table_type=events_table_type)),
            ],
        )
        self.assertEqual(
            node.select_queries[1].select,
            [
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table_type=events_table_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table_type=events_table_type)),
            ],
        )
