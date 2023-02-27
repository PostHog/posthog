from posthog.hogql import ast
from posthog.hogql.database import database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_pointers
from posthog.test.base import BaseTest


class TestResolver(BaseTest):
    def test_resolve_events_table(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        resolve_pointers(expr)

        events_table_pointer = ast.TablePointer(table=database.events)
        event_field_pointer = ast.FieldPointer(name="event", table=events_table_pointer)
        timestamp_field_pointer = ast.FieldPointer(name="timestamp", table=events_table_pointer)
        select_query_pointer = ast.SelectQueryPointer(
            columns={"event": event_field_pointer, "timestamp": timestamp_field_pointer},
            tables={"events": events_table_pointer},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], pointer=event_field_pointer),
                ast.Field(chain=["events", "timestamp"], pointer=timestamp_field_pointer),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                pointer=events_table_pointer,
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["events", "event"], pointer=event_field_pointer),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", pointer=ast.ConstantPointer(value="test")),
            ),
            pointer=select_query_pointer,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_alias(self):
        expr = parse_select("SELECT event, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_pointers(expr)

        events_table_pointer = ast.TablePointer(table=database.events)
        events_table_alias_pointer = ast.TableAliasPointer(name="e", table_pointer=events_table_pointer)
        event_field_pointer = ast.FieldPointer(name="event", table=events_table_alias_pointer)
        timestamp_field_pointer = ast.FieldPointer(name="timestamp", table=events_table_alias_pointer)
        select_query_pointer = ast.SelectQueryPointer(
            columns={"event": event_field_pointer, "timestamp": timestamp_field_pointer},
            tables={"e": events_table_alias_pointer},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], pointer=event_field_pointer),
                ast.Field(chain=["e", "timestamp"], pointer=timestamp_field_pointer),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                alias="e",
                pointer=events_table_alias_pointer,
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], pointer=event_field_pointer),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", pointer=ast.ConstantPointer(value="test")),
            ),
            pointer=select_query_pointer,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias(self):
        expr = parse_select("SELECT event as ee, ee, ee as e, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_pointers(expr)

        events_table_pointer = ast.TablePointer(table=database.events)
        events_table_alias_pointer = ast.TableAliasPointer(name="e", table_pointer=events_table_pointer)
        event_field_pointer = ast.FieldPointer(name="event", table=events_table_alias_pointer)
        timestamp_field_pointer = ast.FieldPointer(name="timestamp", table=events_table_alias_pointer)

        select_query_pointer = ast.SelectQueryPointer(
            aliases={
                "ee": ast.FieldAliasPointer(name="ee", pointer=event_field_pointer),
                "e": ast.FieldAliasPointer(
                    name="e", pointer=ast.FieldAliasPointer(name="ee", pointer=event_field_pointer)
                ),
            },
            columns={
                "ee": ast.FieldAliasPointer(name="ee", pointer=event_field_pointer),
                "e": ast.FieldAliasPointer(
                    name="e", pointer=ast.FieldAliasPointer(name="ee", pointer=event_field_pointer)
                ),
                "timestamp": timestamp_field_pointer,
            },
            tables={"e": events_table_alias_pointer},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="ee",
                    expr=ast.Field(chain=["event"], pointer=event_field_pointer),
                    pointer=select_query_pointer.aliases["ee"],
                ),
                ast.Field(chain=["ee"], pointer=select_query_pointer.aliases["ee"]),
                ast.Alias(
                    alias="e",
                    expr=ast.Field(chain=["ee"], pointer=select_query_pointer.aliases["ee"]),
                    pointer=select_query_pointer.aliases["e"],  # is ee ?
                ),
                ast.Field(chain=["e", "timestamp"], pointer=timestamp_field_pointer),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                alias="e",
                pointer=select_query_pointer.tables["e"],
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], pointer=event_field_pointer),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", pointer=ast.ConstantPointer(value="test")),
            ),
            pointer=select_query_pointer,
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias_inside_subquery(self):
        expr = parse_select("SELECT b FROM (select event as b, timestamp as c from events) e WHERE e.b = 'test'")
        resolve_pointers(expr)
        inner_events_table_pointer = ast.TablePointer(table=database.events)
        inner_event_field_pointer = ast.FieldAliasPointer(
            name="b", pointer=ast.FieldPointer(name="event", table=inner_events_table_pointer)
        )
        timestamp_field_pointer = ast.FieldPointer(name="timestamp", table=inner_events_table_pointer)
        timstamp_alias_pointer = ast.FieldAliasPointer(name="c", pointer=timestamp_field_pointer)
        inner_select_pointer = ast.SelectQueryPointer(
            aliases={
                "b": inner_event_field_pointer,
                "c": ast.FieldAliasPointer(name="c", pointer=timestamp_field_pointer),
            },
            columns={
                "b": inner_event_field_pointer,
                "c": ast.FieldAliasPointer(name="c", pointer=timestamp_field_pointer),
            },
            tables={
                "events": inner_events_table_pointer,
            },
        )
        select_alias_pointer = ast.SelectQueryAliasPointer(name="e", pointer=inner_select_pointer)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["b"],
                    pointer=ast.FieldPointer(
                        name="b",
                        table=ast.SelectQueryAliasPointer(name="e", pointer=inner_select_pointer),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="b",
                            expr=ast.Field(chain=["event"], pointer=inner_event_field_pointer.pointer),
                            pointer=inner_event_field_pointer,
                        ),
                        ast.Alias(
                            alias="c",
                            expr=ast.Field(chain=["timestamp"], pointer=timestamp_field_pointer),
                            pointer=timstamp_alias_pointer,
                        ),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"], pointer=inner_events_table_pointer),
                        pointer=inner_events_table_pointer,
                    ),
                    pointer=inner_select_pointer,
                ),
                alias="e",
                pointer=select_alias_pointer,
            ),
            where=ast.CompareOperation(
                left=ast.Field(
                    chain=["e", "b"],
                    pointer=ast.FieldPointer(name="b", table=select_alias_pointer),
                ),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", pointer=ast.ConstantPointer(value="test")),
            ),
            pointer=ast.SelectQueryPointer(
                aliases={},
                columns={"b": ast.FieldPointer(name="b", table=select_alias_pointer)},
                tables={"e": select_alias_pointer},
            ),
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_subquery_no_field_access(self):
        # From ClickHouse's GitHub: "Aliases defined outside of subquery are not visible in subqueries (but see below)."
        expr = parse_select(
            "SELECT event, (select count() from events where event = e.event) as c FROM events e where event = '$pageview'"
        )
        with self.assertRaises(ResolverException) as e:
            resolve_pointers(expr)
        self.assertEqual(str(e.exception), "Unable to resolve field: e")

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
                resolve_pointers(parse_select(query))
            self.assertIn("Unable to resolve field:", str(e.exception))

    def test_resolve_lazy_pdi_person_table(self):
        expr = parse_select("select distinct_id, person.id from person_distinct_ids")
        resolve_pointers(expr)
        pdi_table_pointer = ast.TablePointer(table=database.person_distinct_ids)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["distinct_id"],
                    pointer=ast.FieldPointer(name="distinct_id", table=pdi_table_pointer),
                ),
                ast.Field(
                    chain=["person", "id"],
                    pointer=ast.FieldPointer(
                        name="id",
                        table=ast.LazyTablePointer(
                            table=pdi_table_pointer, field="person", lazy_table=database.person_distinct_ids.person
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["person_distinct_ids"], pointer=pdi_table_pointer),
                pointer=pdi_table_pointer,
            ),
            pointer=ast.SelectQueryPointer(
                aliases={},
                anonymous_tables=[],
                columns={
                    "distinct_id": ast.FieldPointer(name="distinct_id", table=pdi_table_pointer),
                    "id": ast.FieldPointer(
                        name="id",
                        table=ast.LazyTablePointer(
                            table=pdi_table_pointer,
                            lazy_table=database.person_distinct_ids.person,
                            field="person",
                        ),
                    ),
                },
                tables={"person_distinct_ids": pdi_table_pointer},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table(self):
        expr = parse_select("select event, pdi.person_id from events")
        resolve_pointers(expr)
        events_table_pointer = ast.TablePointer(table=database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    pointer=ast.FieldPointer(name="event", table=events_table_pointer),
                ),
                ast.Field(
                    chain=["pdi", "person_id"],
                    pointer=ast.FieldPointer(
                        name="person_id",
                        table=ast.LazyTablePointer(
                            table=events_table_pointer, field="pdi", lazy_table=database.events.pdi
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                pointer=events_table_pointer,
            ),
            pointer=ast.SelectQueryPointer(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldPointer(name="event", table=events_table_pointer),
                    "person_id": ast.FieldPointer(
                        name="person_id",
                        table=ast.LazyTablePointer(
                            table=events_table_pointer,
                            lazy_table=database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"events": events_table_pointer},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table_aliased(self):
        expr = parse_select("select event, e.pdi.person_id from events e")
        resolve_pointers(expr)
        events_table_pointer = ast.TablePointer(table=database.events)
        events_table_alias_pointer = ast.TableAliasPointer(table_pointer=events_table_pointer, name="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    pointer=ast.FieldPointer(name="event", table=events_table_alias_pointer),
                ),
                ast.Field(
                    chain=["e", "pdi", "person_id"],
                    pointer=ast.FieldPointer(
                        name="person_id",
                        table=ast.LazyTablePointer(
                            table=events_table_alias_pointer, field="pdi", lazy_table=database.events.pdi
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                alias="e",
                pointer=events_table_alias_pointer,
            ),
            pointer=ast.SelectQueryPointer(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldPointer(name="event", table=events_table_alias_pointer),
                    "person_id": ast.FieldPointer(
                        name="person_id",
                        table=ast.LazyTablePointer(
                            table=events_table_alias_pointer,
                            lazy_table=database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"e": events_table_alias_pointer},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table(self):
        expr = parse_select("select event, pdi.person.id from events")
        resolve_pointers(expr)
        events_table_pointer = ast.TablePointer(table=database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    pointer=ast.FieldPointer(name="event", table=events_table_pointer),
                ),
                ast.Field(
                    chain=["pdi", "person", "id"],
                    pointer=ast.FieldPointer(
                        name="id",
                        table=ast.LazyTablePointer(
                            table=ast.LazyTablePointer(
                                table=events_table_pointer, field="pdi", lazy_table=database.events.pdi
                            ),
                            field="person",
                            lazy_table=database.events.pdi.table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                pointer=events_table_pointer,
            ),
            pointer=ast.SelectQueryPointer(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldPointer(name="event", table=events_table_pointer),
                    "id": ast.FieldPointer(
                        name="id",
                        table=ast.LazyTablePointer(
                            table=ast.LazyTablePointer(
                                table=events_table_pointer, field="pdi", lazy_table=database.events.pdi
                            ),
                            field="person",
                            lazy_table=database.events.pdi.table.person,
                        ),
                    ),
                },
                tables={"events": events_table_pointer},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table_aliased(self):
        expr = parse_select("select event, e.pdi.person.id from events e")
        resolve_pointers(expr)
        events_table_pointer = ast.TablePointer(table=database.events)
        events_table_alias_pointer = ast.TableAliasPointer(table_pointer=events_table_pointer, name="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    pointer=ast.FieldPointer(name="event", table=events_table_alias_pointer),
                ),
                ast.Field(
                    chain=["e", "pdi", "person", "id"],
                    pointer=ast.FieldPointer(
                        name="id",
                        table=ast.LazyTablePointer(
                            table=ast.LazyTablePointer(
                                table=events_table_alias_pointer, field="pdi", lazy_table=database.events.pdi
                            ),
                            field="person",
                            lazy_table=database.events.pdi.table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                alias="e",
                pointer=events_table_alias_pointer,
            ),
            pointer=ast.SelectQueryPointer(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldPointer(name="event", table=events_table_alias_pointer),
                    "id": ast.FieldPointer(
                        name="id",
                        table=ast.LazyTablePointer(
                            table=ast.LazyTablePointer(
                                table=events_table_alias_pointer, field="pdi", lazy_table=database.events.pdi
                            ),
                            field="person",
                            lazy_table=database.events.pdi.table.person,
                        ),
                    ),
                },
                tables={"e": events_table_alias_pointer},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)

    def test_resolve_virtual_events_poe(self):
        expr = parse_select("select event, poe.id from events")
        resolve_pointers(expr)
        events_table_pointer = ast.TablePointer(table=database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    pointer=ast.FieldPointer(name="event", table=events_table_pointer),
                ),
                ast.Field(
                    chain=["poe", "id"],
                    pointer=ast.FieldPointer(
                        name="id",
                        table=ast.VirtualTablePointer(
                            table=events_table_pointer, field="poe", virtual_table=database.events.poe
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], pointer=events_table_pointer),
                pointer=events_table_pointer,
            ),
            pointer=ast.SelectQueryPointer(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldPointer(name="event", table=events_table_pointer),
                    "id": ast.FieldPointer(
                        name="id",
                        table=ast.VirtualTablePointer(
                            table=events_table_pointer, field="poe", virtual_table=database.events.poe
                        ),
                    ),
                },
                tables={"events": events_table_pointer},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.pointer, expected.pointer)
        self.assertEqual(expr, expected)
