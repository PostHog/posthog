from datetime import timezone, datetime, date
from uuid import UUID

from freezegun import freeze_time

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.hogql.resolver import ResolverException, resolve_types
from posthog.test.base import BaseTest


class TestResolver(BaseTest):
    def setUp(self):
        self.database = create_hogql_database(self.team.pk)

    def test_resolve_events_table(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        expr = resolve_types(expr, self.database)

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
                right=ast.Constant(value="test", type=ast.StringType()),
                type=ast.BooleanType(),
            ),
            type=select_query_type,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.type, expected.type)
        self.assertEqual(expr, expected)

    def test_will_not_run_twice(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        expr = resolve_types(expr, self.database)
        with self.assertRaises(ResolverException) as context:
            expr = resolve_types(expr, self.database)
        self.assertEqual(
            str(context.exception), "Type already resolved for SelectQuery (SelectQueryType). Can't run again."
        )

    def test_resolve_events_table_alias(self):
        expr = parse_select("SELECT event, e.timestamp FROM events e WHERE e.event = 'test'")
        expr = resolve_types(expr, database=self.database)

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
                right=ast.Constant(value="test", type=ast.StringType()),
                type=ast.BooleanType(),
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
        expr = resolve_types(expr, database=self.database)

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
                right=ast.Constant(value="test", type=ast.StringType()),
                type=ast.BooleanType(),
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
        expr = resolve_types(expr, database=self.database)
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
                right=ast.Constant(value="test", type=ast.StringType()),
                type=ast.BooleanType(),
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
            expr = resolve_types(expr, database=self.database)
        self.assertEqual(str(e.exception), "Unable to resolve field: e")

    def test_resolve_constant_type(self):
        with freeze_time("2020-01-10 00:00:00"):
            expr = parse_select(
                "SELECT 1, 'boo', true, 1.1232, null, {date}, {datetime}, {uuid}, {array}, {array12}, {tuple}",
                placeholders={
                    "date": ast.Constant(value=date(2020, 1, 10)),
                    "datetime": ast.Constant(value=datetime(2020, 1, 10, 0, 0, 0, tzinfo=timezone.utc)),
                    "uuid": ast.Constant(value=UUID("00000000-0000-4000-8000-000000000000")),
                    "array": ast.Constant(value=[]),
                    "array12": ast.Constant(value=[1, 2]),
                    "tuple": ast.Constant(value=(1, 2, 3)),
                },
            )
            expr = resolve_types(expr, database=self.database)
            expected = ast.SelectQuery(
                select=[
                    ast.Constant(value=1, type=ast.IntegerType()),
                    ast.Constant(value="boo", type=ast.StringType()),
                    ast.Constant(value=True, type=ast.BooleanType()),
                    ast.Constant(value=1.1232, type=ast.FloatType()),
                    ast.Constant(value=None, type=ast.UnknownType()),
                    ast.Constant(value=date(2020, 1, 10), type=ast.DateType()),
                    ast.Constant(value=datetime(2020, 1, 10, 0, 0, 0, tzinfo=timezone.utc), type=ast.DateTimeType()),
                    ast.Constant(value=UUID("00000000-0000-4000-8000-000000000000"), type=ast.UUIDType()),
                    ast.Constant(value=[], type=ast.ArrayType(item_type=ast.UnknownType())),
                    ast.Constant(value=[1, 2], type=ast.ArrayType(item_type=ast.IntegerType())),
                    ast.Constant(
                        value=(1, 2, 3),
                        type=ast.TupleType(item_types=[ast.IntegerType(), ast.IntegerType(), ast.IntegerType()]),
                    ),
                ],
                type=ast.SelectQueryType(aliases={}, columns={}, tables={}),
            )
            self.assertEqual(expr, expected)

    def test_resolve_boolean_operation_types(self):
        expr = parse_select("SELECT 1 and 1, 1 or 1, not true")
        expr = resolve_types(expr, database=self.database)
        expected = ast.SelectQuery(
            select=[
                ast.And(
                    exprs=[
                        ast.Constant(value=1, type=ast.IntegerType()),
                        ast.Constant(value=1, type=ast.IntegerType()),
                    ],
                    type=ast.BooleanType(),
                ),
                ast.Or(
                    exprs=[
                        ast.Constant(value=1, type=ast.IntegerType()),
                        ast.Constant(value=1, type=ast.IntegerType()),
                    ],
                    type=ast.BooleanType(),
                ),
                ast.Not(
                    expr=ast.Constant(value=True, type=ast.BooleanType()),
                    type=ast.BooleanType(),
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
        expr = resolve_types(expr, database=self.database)
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
        expr = resolve_types(expr, database=self.database)
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
        expr = resolve_types(expr, database=self.database)
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
        expr = resolve_types(expr, database=self.database)
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
        expr = resolve_types(expr, database=self.database)
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
        expr = resolve_types(expr, database=self.database)
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
        node = resolve_types(node, self.database)

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

    def test_call_type(self):
        node = parse_select("select max(timestamp) from events")
        node = resolve_types(node, self.database)
        expected = [
            ast.Call(
                name="max",
                # NB! timestamp was resolved to a DateTimeType for the Call's arg type.
                type=ast.CallType(name="max", arg_types=[ast.DateTimeType()], return_type=ast.UnknownType()),
                args=[
                    ast.Field(
                        chain=["timestamp"],
                        type=ast.FieldType(name="timestamp", table_type=ast.TableType(table=self.database.events)),
                    )
                ],
            ),
        ]
        self.assertEqual(node.select, expected)

    def test_macros_loop(self):
        with self.assertRaises(ResolverException) as e:
            self._print_hogql("with macro as (select * from macro) select * from macro")
        self.assertIn("Too many macro expansions (50+). Probably a macro loop.", str(e.exception))

    def test_macros_basic_column(self):
        expr = self._print_hogql("with 1 as macro select macro from events")
        expected = self._print_hogql("select 1 from events")
        self.assertEqual(
            expr,
            expected,
        )

    def test_macros_recursive_column(self):
        self.assertEqual(
            self._print_hogql("with 1 as macro, macro as soap select soap from events"),
            self._print_hogql("select 1 from events"),
        )

    def test_macros_field_access(self):
        with self.assertRaises(ResolverException) as e:
            self._print_hogql("with properties as macro select macro.$browser from events")
        self.assertIn("Cannot access fields on macro macro yet.", str(e.exception))

    def test_macros_subqueries(self):
        self.assertEqual(
            self._print_hogql("with my_table as (select * from events) select * from my_table"),
            self._print_hogql("select * from (select * from events) my_table"),
        )

        self.assertEqual(
            self._print_hogql("with my_table as (select * from events) select my_table.timestamp from my_table"),
            self._print_hogql("select my_table.timestamp from (select * from events) my_table"),
        )

        self.assertEqual(
            self._print_hogql("with my_table as (select * from events) select timestamp from my_table"),
            self._print_hogql("select timestamp from (select * from events) my_table"),
        )

    def test_macros_subquery_deep(self):
        self.assertEqual(
            self._print_hogql(
                "with my_table as (select * from events), "
                "other_table as (select * from (select * from (select * from my_table))) "
                "select * from other_table"
            ),
            self._print_hogql(
                "select * from (select * from (select * from (select * from (select * from events) as my_table))) as other_table"
            ),
        )

    def test_macros_subquery_recursion(self):
        self.assertEqual(
            self._print_hogql(
                "with users as (select event, timestamp as tt from events ), final as ( select tt from users ) select * from final"
            ),
            self._print_hogql(
                "select * from (select tt from (select event, timestamp as tt from events) AS users) AS final"
            ),
        )

    def test_asterisk_expander_table(self):
        node = parse_select("select * from events")
        node = resolve_types(node, self.database)

        events_table_type = ast.TableType(table=self.database.events)
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table_type=events_table_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table_type=events_table_type)),
                ast.Field(chain=["properties"], type=ast.FieldType(name="properties", table_type=events_table_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table_type=events_table_type)),
                ast.Field(chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table_type=events_table_type)),
                ast.Field(
                    chain=["elements_chain"], type=ast.FieldType(name="elements_chain", table_type=events_table_type)
                ),
                ast.Field(chain=["created_at"], type=ast.FieldType(name="created_at", table_type=events_table_type)),
            ],
        )

    def test_asterisk_expander_table_alias(self):
        node = parse_select("select * from events e")
        node = resolve_types(node, self.database)

        events_table_type = ast.TableType(table=self.database.events)
        events_table_alias_type = ast.TableAliasType(table_type=events_table_type, alias="e")
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table_type=events_table_alias_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table_type=events_table_alias_type)),
                ast.Field(
                    chain=["properties"], type=ast.FieldType(name="properties", table_type=events_table_alias_type)
                ),
                ast.Field(
                    chain=["timestamp"], type=ast.FieldType(name="timestamp", table_type=events_table_alias_type)
                ),
                ast.Field(
                    chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table_type=events_table_alias_type)
                ),
                ast.Field(
                    chain=["elements_chain"],
                    type=ast.FieldType(name="elements_chain", table_type=events_table_alias_type),
                ),
                ast.Field(
                    chain=["created_at"], type=ast.FieldType(name="created_at", table_type=events_table_alias_type)
                ),
            ],
        )

    def test_asterisk_expander_subquery(self):
        node = parse_select("select * from (select 1 as a, 2 as b)")
        node = resolve_types(node, self.database)
        select_subquery_type = ast.SelectQueryType(
            aliases={
                "a": ast.FieldAliasType(alias="a", type=ast.ConstantType(data_type="int")),
                "b": ast.FieldAliasType(alias="b", type=ast.ConstantType(data_type="int")),
            },
            columns={
                "a": ast.FieldAliasType(alias="a", type=ast.ConstantType(data_type="int")),
                "b": ast.FieldAliasType(alias="b", type=ast.ConstantType(data_type="int")),
            },
            tables={},
            anonymous_tables=[],
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], type=ast.FieldType(name="a", table_type=select_subquery_type)),
                ast.Field(chain=["b"], type=ast.FieldType(name="b", table_type=select_subquery_type)),
            ],
        )

    def test_asterisk_expander_subquery_alias(self):
        node = parse_select("select x.* from (select 1 as a, 2 as b) x")
        node = resolve_types(node, self.database)
        select_subquery_type = ast.SelectQueryAliasType(
            alias="x",
            select_query_type=ast.SelectQueryType(
                aliases={
                    "a": ast.FieldAliasType(alias="a", type=ast.ConstantType(data_type="int")),
                    "b": ast.FieldAliasType(alias="b", type=ast.ConstantType(data_type="int")),
                },
                columns={
                    "a": ast.FieldAliasType(alias="a", type=ast.ConstantType(data_type="int")),
                    "b": ast.FieldAliasType(alias="b", type=ast.ConstantType(data_type="int")),
                },
                tables={},
                anonymous_tables=[],
            ),
        )
        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["a"], type=ast.FieldType(name="a", table_type=select_subquery_type)),
                ast.Field(chain=["b"], type=ast.FieldType(name="b", table_type=select_subquery_type)),
            ],
        )

    def test_asterisk_expander_from_subquery_table(self):
        node = parse_select("select * from (select * from events)")
        node = resolve_types(node, self.database)

        events_table_type = ast.TableType(table=self.database.events)
        inner_select_type = ast.SelectQueryType(
            tables={"events": events_table_type},
            anonymous_tables=[],
            aliases={},
            columns={
                "uuid": ast.FieldType(name="uuid", table_type=events_table_type),
                "event": ast.FieldType(name="event", table_type=events_table_type),
                "properties": ast.FieldType(name="properties", table_type=events_table_type),
                "timestamp": ast.FieldType(name="timestamp", table_type=events_table_type),
                "distinct_id": ast.FieldType(name="distinct_id", table_type=events_table_type),
                "elements_chain": ast.FieldType(name="elements_chain", table_type=events_table_type),
                "created_at": ast.FieldType(name="created_at", table_type=events_table_type),
            },
        )

        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table_type=inner_select_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table_type=inner_select_type)),
                ast.Field(chain=["properties"], type=ast.FieldType(name="properties", table_type=inner_select_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table_type=inner_select_type)),
                ast.Field(chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table_type=inner_select_type)),
                ast.Field(
                    chain=["elements_chain"],
                    type=ast.FieldType(name="elements_chain", table_type=inner_select_type),
                ),
                ast.Field(chain=["created_at"], type=ast.FieldType(name="created_at", table_type=inner_select_type)),
            ],
        )

    def test_asterisk_expander_multiple_table_error(self):
        node = parse_select("select * from (select 1 as a, 2 as b) x left join (select 1 as a, 2 as b) y on x.a = y.a")
        with self.assertRaises(ResolverException) as e:
            resolve_types(node, self.database)
        self.assertEqual(
            str(e.exception), "Cannot use '*' without table name when there are multiple tables in the query"
        )

    def test_asterisk_expander_select_union(self):
        node = parse_select("select * from (select * from events union all select * from events)")
        node = resolve_types(node, self.database)

        events_table_type = ast.TableType(table=self.database.events)
        inner_select_type = ast.SelectUnionQueryType(
            types=[
                ast.SelectQueryType(
                    tables={"events": events_table_type},
                    anonymous_tables=[],
                    aliases={},
                    columns={
                        "uuid": ast.FieldType(name="uuid", table_type=events_table_type),
                        "event": ast.FieldType(name="event", table_type=events_table_type),
                        "properties": ast.FieldType(name="properties", table_type=events_table_type),
                        "timestamp": ast.FieldType(name="timestamp", table_type=events_table_type),
                        "distinct_id": ast.FieldType(name="distinct_id", table_type=events_table_type),
                        "elements_chain": ast.FieldType(name="elements_chain", table_type=events_table_type),
                        "created_at": ast.FieldType(name="created_at", table_type=events_table_type),
                    },
                )
            ]
            * 2
        )

        self.assertEqual(
            node.select,
            [
                ast.Field(chain=["uuid"], type=ast.FieldType(name="uuid", table_type=inner_select_type)),
                ast.Field(chain=["event"], type=ast.FieldType(name="event", table_type=inner_select_type)),
                ast.Field(chain=["properties"], type=ast.FieldType(name="properties", table_type=inner_select_type)),
                ast.Field(chain=["timestamp"], type=ast.FieldType(name="timestamp", table_type=inner_select_type)),
                ast.Field(chain=["distinct_id"], type=ast.FieldType(name="distinct_id", table_type=inner_select_type)),
                ast.Field(
                    chain=["elements_chain"],
                    type=ast.FieldType(name="elements_chain", table_type=inner_select_type),
                ),
                ast.Field(chain=["created_at"], type=ast.FieldType(name="created_at", table_type=inner_select_type)),
            ],
        )

    def _print_hogql(self, select: str):
        expr = parse_select(select)
        return print_ast(expr, HogQLContext(team_id=self.team.pk, enable_select_queries=True), "hogql")
