from posthog.hogql import ast
from posthog.hogql.database import create_hogql_database
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import ResolverException, resolve_refs
from posthog.test.base import BaseTest


class TestResolver(BaseTest):
    def setUp(self):
        self.database = create_hogql_database(self.team.pk)

    def test_resolve_events_table(self):
        expr = parse_select("SELECT event, events.timestamp FROM events WHERE events.event = 'test'")
        resolve_refs(expr, self.database)

        events_table_ref = ast.TableRef(table=self.database.events)
        event_field_ref = ast.FieldRef(name="event", table=events_table_ref)
        timestamp_field_ref = ast.FieldRef(name="timestamp", table=events_table_ref)
        select_query_ref = ast.SelectQueryRef(
            columns={"event": event_field_ref, "timestamp": timestamp_field_ref},
            tables={"events": events_table_ref},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], ref=event_field_ref),
                ast.Field(chain=["events", "timestamp"], ref=timestamp_field_ref),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                ref=events_table_ref,
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["events", "event"], ref=event_field_ref),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", ref=ast.ConstantRef(value="test")),
            ),
            ref=select_query_ref,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_alias(self):
        expr = parse_select("SELECT event, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_refs(expr, database=self.database)

        events_table_ref = ast.TableRef(table=self.database.events)
        events_table_alias_ref = ast.TableAliasRef(name="e", table_ref=events_table_ref)
        event_field_ref = ast.FieldRef(name="event", table=events_table_alias_ref)
        timestamp_field_ref = ast.FieldRef(name="timestamp", table=events_table_alias_ref)
        select_query_ref = ast.SelectQueryRef(
            columns={"event": event_field_ref, "timestamp": timestamp_field_ref},
            tables={"e": events_table_alias_ref},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Field(chain=["event"], ref=event_field_ref),
                ast.Field(chain=["e", "timestamp"], ref=timestamp_field_ref),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                alias="e",
                ref=events_table_alias_ref,
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], ref=event_field_ref),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", ref=ast.ConstantRef(value="test")),
            ),
            ref=select_query_ref,
        )

        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias(self):
        expr = parse_select("SELECT event as ee, ee, ee as e, e.timestamp FROM events e WHERE e.event = 'test'")
        resolve_refs(expr, database=self.database)

        events_table_ref = ast.TableRef(table=self.database.events)
        events_table_alias_ref = ast.TableAliasRef(name="e", table_ref=events_table_ref)
        event_field_ref = ast.FieldRef(name="event", table=events_table_alias_ref)
        timestamp_field_ref = ast.FieldRef(name="timestamp", table=events_table_alias_ref)

        select_query_ref = ast.SelectQueryRef(
            aliases={
                "ee": ast.FieldAliasRef(name="ee", ref=event_field_ref),
                "e": ast.FieldAliasRef(name="e", ref=ast.FieldAliasRef(name="ee", ref=event_field_ref)),
            },
            columns={
                "ee": ast.FieldAliasRef(name="ee", ref=event_field_ref),
                "e": ast.FieldAliasRef(name="e", ref=ast.FieldAliasRef(name="ee", ref=event_field_ref)),
                "timestamp": timestamp_field_ref,
            },
            tables={"e": events_table_alias_ref},
        )

        expected = ast.SelectQuery(
            select=[
                ast.Alias(
                    alias="ee",
                    expr=ast.Field(chain=["event"], ref=event_field_ref),
                    ref=select_query_ref.aliases["ee"],
                ),
                ast.Field(chain=["ee"], ref=select_query_ref.aliases["ee"]),
                ast.Alias(
                    alias="e",
                    expr=ast.Field(chain=["ee"], ref=select_query_ref.aliases["ee"]),
                    ref=select_query_ref.aliases["e"],  # is ee ?
                ),
                ast.Field(chain=["e", "timestamp"], ref=timestamp_field_ref),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                alias="e",
                ref=select_query_ref.tables["e"],
            ),
            where=ast.CompareOperation(
                left=ast.Field(chain=["e", "event"], ref=event_field_ref),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", ref=ast.ConstantRef(value="test")),
            ),
            ref=select_query_ref,
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_events_table_column_alias_inside_subquery(self):
        expr = parse_select("SELECT b FROM (select event as b, timestamp as c from events) e WHERE e.b = 'test'")
        resolve_refs(expr, database=self.database)
        inner_events_table_ref = ast.TableRef(table=self.database.events)
        inner_event_field_ref = ast.FieldAliasRef(
            name="b", ref=ast.FieldRef(name="event", table=inner_events_table_ref)
        )
        timestamp_field_ref = ast.FieldRef(name="timestamp", table=inner_events_table_ref)
        timstamp_alias_ref = ast.FieldAliasRef(name="c", ref=timestamp_field_ref)
        inner_select_ref = ast.SelectQueryRef(
            aliases={
                "b": inner_event_field_ref,
                "c": ast.FieldAliasRef(name="c", ref=timestamp_field_ref),
            },
            columns={
                "b": inner_event_field_ref,
                "c": ast.FieldAliasRef(name="c", ref=timestamp_field_ref),
            },
            tables={
                "events": inner_events_table_ref,
            },
        )
        select_alias_ref = ast.SelectQueryAliasRef(name="e", ref=inner_select_ref)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["b"],
                    ref=ast.FieldRef(
                        name="b",
                        table=ast.SelectQueryAliasRef(name="e", ref=inner_select_ref),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="b",
                            expr=ast.Field(chain=["event"], ref=inner_event_field_ref.ref),
                            ref=inner_event_field_ref,
                        ),
                        ast.Alias(
                            alias="c",
                            expr=ast.Field(chain=["timestamp"], ref=timestamp_field_ref),
                            ref=timstamp_alias_ref,
                        ),
                    ],
                    select_from=ast.JoinExpr(
                        table=ast.Field(chain=["events"], ref=inner_events_table_ref),
                        ref=inner_events_table_ref,
                    ),
                    ref=inner_select_ref,
                ),
                alias="e",
                ref=select_alias_ref,
            ),
            where=ast.CompareOperation(
                left=ast.Field(
                    chain=["e", "b"],
                    ref=ast.FieldRef(name="b", table=select_alias_ref),
                ),
                op=ast.CompareOperationType.Eq,
                right=ast.Constant(value="test", ref=ast.ConstantRef(value="test")),
            ),
            ref=ast.SelectQueryRef(
                aliases={},
                columns={"b": ast.FieldRef(name="b", table=select_alias_ref)},
                tables={"e": select_alias_ref},
            ),
        )
        # asserting individually to help debug if something is off
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_subquery_no_field_access(self):
        # From ClickHouse's GitHub: "Aliases defined outside of subquery are not visible in subqueries (but see below)."
        expr = parse_select(
            "SELECT event, (select count() from events where event = e.event) as c FROM events e where event = '$pageview'"
        )
        with self.assertRaises(ResolverException) as e:
            resolve_refs(expr, database=self.database)
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
                resolve_refs(parse_select(query), self.database)
            self.assertIn("Unable to resolve field:", str(e.exception))

    def test_resolve_lazy_pdi_person_table(self):
        expr = parse_select("select distinct_id, person.id from person_distinct_ids")
        resolve_refs(expr, database=self.database)
        pdi_table_ref = ast.TableRef(table=self.database.person_distinct_ids)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["distinct_id"],
                    ref=ast.FieldRef(name="distinct_id", table=pdi_table_ref),
                ),
                ast.Field(
                    chain=["person", "id"],
                    ref=ast.FieldRef(
                        name="id",
                        table=ast.LazyJoinRef(
                            table=pdi_table_ref, field="person", lazy_join=self.database.person_distinct_ids.person
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["person_distinct_ids"], ref=pdi_table_ref),
                ref=pdi_table_ref,
            ),
            ref=ast.SelectQueryRef(
                aliases={},
                anonymous_tables=[],
                columns={
                    "distinct_id": ast.FieldRef(name="distinct_id", table=pdi_table_ref),
                    "id": ast.FieldRef(
                        name="id",
                        table=ast.LazyJoinRef(
                            table=pdi_table_ref,
                            lazy_join=self.database.person_distinct_ids.person,
                            field="person",
                        ),
                    ),
                },
                tables={"person_distinct_ids": pdi_table_ref},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table(self):
        expr = parse_select("select event, pdi.person_id from events")
        resolve_refs(expr, database=self.database)
        events_table_ref = ast.TableRef(table=self.database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    ref=ast.FieldRef(name="event", table=events_table_ref),
                ),
                ast.Field(
                    chain=["pdi", "person_id"],
                    ref=ast.FieldRef(
                        name="person_id",
                        table=ast.LazyJoinRef(table=events_table_ref, field="pdi", lazy_join=self.database.events.pdi),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                ref=events_table_ref,
            ),
            ref=ast.SelectQueryRef(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldRef(name="event", table=events_table_ref),
                    "person_id": ast.FieldRef(
                        name="person_id",
                        table=ast.LazyJoinRef(
                            table=events_table_ref,
                            lazy_join=self.database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"events": events_table_ref},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_table_aliased(self):
        expr = parse_select("select event, e.pdi.person_id from events e")
        resolve_refs(expr, database=self.database)
        events_table_ref = ast.TableRef(table=self.database.events)
        events_table_alias_ref = ast.TableAliasRef(table_ref=events_table_ref, name="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    ref=ast.FieldRef(name="event", table=events_table_alias_ref),
                ),
                ast.Field(
                    chain=["e", "pdi", "person_id"],
                    ref=ast.FieldRef(
                        name="person_id",
                        table=ast.LazyJoinRef(
                            table=events_table_alias_ref, field="pdi", lazy_join=self.database.events.pdi
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                alias="e",
                ref=events_table_alias_ref,
            ),
            ref=ast.SelectQueryRef(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldRef(name="event", table=events_table_alias_ref),
                    "person_id": ast.FieldRef(
                        name="person_id",
                        table=ast.LazyJoinRef(
                            table=events_table_alias_ref,
                            lazy_join=self.database.events.pdi,
                            field="pdi",
                        ),
                    ),
                },
                tables={"e": events_table_alias_ref},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table(self):
        expr = parse_select("select event, pdi.person.id from events")
        resolve_refs(expr, database=self.database)
        events_table_ref = ast.TableRef(table=self.database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    ref=ast.FieldRef(name="event", table=events_table_ref),
                ),
                ast.Field(
                    chain=["pdi", "person", "id"],
                    ref=ast.FieldRef(
                        name="id",
                        table=ast.LazyJoinRef(
                            table=ast.LazyJoinRef(
                                table=events_table_ref, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                ref=events_table_ref,
            ),
            ref=ast.SelectQueryRef(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldRef(name="event", table=events_table_ref),
                    "id": ast.FieldRef(
                        name="id",
                        table=ast.LazyJoinRef(
                            table=ast.LazyJoinRef(
                                table=events_table_ref, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                },
                tables={"events": events_table_ref},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_lazy_events_pdi_person_table_aliased(self):
        expr = parse_select("select event, e.pdi.person.id from events e")
        resolve_refs(expr, database=self.database)
        events_table_ref = ast.TableRef(table=self.database.events)
        events_table_alias_ref = ast.TableAliasRef(table_ref=events_table_ref, name="e")
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    ref=ast.FieldRef(name="event", table=events_table_alias_ref),
                ),
                ast.Field(
                    chain=["e", "pdi", "person", "id"],
                    ref=ast.FieldRef(
                        name="id",
                        table=ast.LazyJoinRef(
                            table=ast.LazyJoinRef(
                                table=events_table_alias_ref, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                alias="e",
                ref=events_table_alias_ref,
            ),
            ref=ast.SelectQueryRef(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldRef(name="event", table=events_table_alias_ref),
                    "id": ast.FieldRef(
                        name="id",
                        table=ast.LazyJoinRef(
                            table=ast.LazyJoinRef(
                                table=events_table_alias_ref, field="pdi", lazy_join=self.database.events.pdi
                            ),
                            field="person",
                            lazy_join=self.database.events.pdi.join_table.person,
                        ),
                    ),
                },
                tables={"e": events_table_alias_ref},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_virtual_events_poe(self):
        expr = parse_select("select event, poe.id from events")
        resolve_refs(expr, database=self.database)
        events_table_ref = ast.TableRef(table=self.database.events)
        expected = ast.SelectQuery(
            select=[
                ast.Field(
                    chain=["event"],
                    ref=ast.FieldRef(name="event", table=events_table_ref),
                ),
                ast.Field(
                    chain=["poe", "id"],
                    ref=ast.FieldRef(
                        name="id",
                        table=ast.VirtualTableRef(
                            table=events_table_ref, field="poe", virtual_table=self.database.events.poe
                        ),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"], ref=events_table_ref),
                ref=events_table_ref,
            ),
            ref=ast.SelectQueryRef(
                aliases={},
                anonymous_tables=[],
                columns={
                    "event": ast.FieldRef(name="event", table=events_table_ref),
                    "id": ast.FieldRef(
                        name="id",
                        table=ast.VirtualTableRef(
                            table=events_table_ref, field="poe", virtual_table=self.database.events.poe
                        ),
                    ),
                },
                tables={"events": events_table_ref},
            ),
        )
        self.assertEqual(expr.select, expected.select)
        self.assertEqual(expr.select_from, expected.select_from)
        self.assertEqual(expr.where, expected.where)
        self.assertEqual(expr.ref, expected.ref)
        self.assertEqual(expr, expected)

    def test_resolve_union_all(self):
        node = parse_select("select event, timestamp from events union all select event, timestamp from events")
        resolve_refs(node, self.database)

        events_table_ref = ast.TableRef(table=self.database.events)
        self.assertEqual(
            node.select_queries[0].select,
            [
                ast.Field(chain=["event"], ref=ast.FieldRef(name="event", table=events_table_ref)),
                ast.Field(chain=["timestamp"], ref=ast.FieldRef(name="timestamp", table=events_table_ref)),
            ],
        )
        self.assertEqual(
            node.select_queries[1].select,
            [
                ast.Field(chain=["event"], ref=ast.FieldRef(name="event", table=events_table_ref)),
                ast.Field(chain=["timestamp"], ref=ast.FieldRef(name="timestamp", table=events_table_ref)),
            ],
        )
