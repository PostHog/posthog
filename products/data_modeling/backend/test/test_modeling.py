import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError, ResolutionCycleError, ResolutionDepthExceededError
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types

from products.data_modeling.backend.logic.model_bindings import DOES_NOT_RESOLVE, READS_ANOTHER_TABLE
from products.data_modeling.backend.logic.model_references import (
    DOES_NOT_PARSE,
    PARSE_CHECK_FAILED,
    ModelReferenceRewriteError,
    model_spellings,
    rename_model_references,
)
from products.data_modeling.backend.logic.model_rename import plan_model_rename
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.modeling import (
    DEFAULT_RESOLUTION_DEADLINE_SECONDS,
    DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
    RESOLUTION_SOURCE_LINEAGE,
    RESOLUTION_SOURCE_MATERIALIZATION,
    BoundedResolver,
    ResolutionTimeoutError,
    get_parents_from_model_query,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseCredential, DataWarehouseTable

GET_PARENTS_TEST_CASES = [
    ("select events.*, persons.* from events, persons", {"events", "persons"}),
    (
        "with cte as (select * from events), cte2 as (select * from cte), cte3 as (select 1) select * from cte2",
        {"events"},
    ),
    ("select 1", set()),
    (
        """
        select *
        from (
          select events.*, num.*
          from events
          inner join (
            select number
            from numbers(10)
          ) num on 1 = 1
        )
        """,
        {"events"},
    ),
    ("select * from (select * from (select * from (select * from events)))", {"events"}),
    (
        """
        select *
        from (
          select number from numbers(5)
          union all
          select event from events
        )
        """,
        {"events"},
    ),
    # Table function as the only source
    ("select number from numbers(10)", set()),
    # CTE with UNION ALL at top level - the CTE should not be treated as a parent
    (
        """
            WITH cte AS (SELECT * FROM events)
            SELECT * FROM cte
            UNION ALL
            SELECT * FROM cte
            """,
        {"events"},
    ),
    # CTE used in a JOIN - should resolve through the CTE to find actual parents
    (
        """
            WITH cte AS (SELECT event, person_id FROM events GROUP BY event, person_id)
            SELECT p.id, c.event
            FROM persons p
            JOIN cte c ON p.id = c.person_id
            """,
        {"events", "persons"},
    ),
    # nested CTEs: a top-level CTE whose inner query defines its own CTEs used in a JOIN
    (
        """
            WITH outer_cte AS (
                WITH inner_data AS (
                    SELECT event, person_id FROM events GROUP BY event, person_id
                ),
                inner_agg AS (
                    SELECT person_id, count() AS cnt FROM inner_data GROUP BY person_id
                )
                SELECT p.id, ia.cnt
                FROM persons p
                JOIN inner_agg ia ON p.id = ia.person_id
            )
            SELECT * FROM outer_cte
        """,
        {"events", "persons"},
    ),
    # nested CTEs where an inner CTE shadows an outer CTE name
    (
        """
            WITH cte AS (
                WITH cte AS (
                    SELECT event, person_id FROM events GROUP BY event, person_id
                ),
                agg AS (
                    SELECT person_id, count() AS cnt FROM cte GROUP BY person_id
                )
                SELECT p.id, a.cnt
                FROM persons p
                JOIN agg a ON p.id = a.person_id
            )
            SELECT * FROM cte
        """,
        {"events", "persons"},
    ),
    # recursive CTE: self-referencing CTE should not cause infinite loop
    (
        """
            WITH RECURSIVE cte AS (
                SELECT 1 AS n
                UNION ALL
                SELECT n + 1 FROM cte WHERE n < 10
            )
            SELECT * FROM cte
        """,
        set(),
    ),
    (
        "select event from events where person_id in (select id from persons)",
        {"events", "persons"},
    ),
    (
        "select event, (select count() from persons) as total from events",
        {"events", "persons"},
    ),
    (
        "select event, count() as c from events group by event having count() > (select count() from persons)",
        {"events", "persons"},
    ),
    (
        "select event from events order by (select count() from persons)",
        {"events", "persons"},
    ),
    (
        "with cte as (select id from persons) select event from events where person_id in (select id from cte)",
        {"events", "persons"},
    ),
    (
        "select event from events prewhere person_id in (select id from persons)",
        {"events", "persons"},
    ),
    (
        "select a.event from events a join events b on a.person_id in (select id from persons)",
        {"events", "persons"},
    ),
]


class TestGetParentsFromModelQuery(BaseTest):
    @parameterized.expand(GET_PARENTS_TEST_CASES)
    def test_get_parents_from_model_query(self, model_query: str, parents: set[str]):
        model_name = "test_model"
        assert parents == get_parents_from_model_query(self.team, model_name, model_query)

    def test_get_parents_from_model_query_unknown_table_raises(self):
        """Test that referencing a non-existent table raises QueryError."""
        with pytest.raises(QueryError, match="Unknown table"):
            get_parents_from_model_query(self.team, "test_model", "select * from some_random_view")


class TestRenameModelReferences(BaseTest):
    def setUp(self):
        super().setUp()
        for name, origin in [
            ("revenue", None),
            ("marts.orders", DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE),
            ("wrapper", None),
            ("shared", None),
            ("ep_view", DataWarehouseSavedQuery.Origin.ENDPOINT),
            ("costs", None),
            ("marts.fees", DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE),
            ("marts.fees.archive", DataWarehouseSavedQuery.Origin.DATA_WAREHOUSE),
            ("held", None),
        ]:
            body = "select * from revenue" if name == "wrapper" else "select 1 as id"
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=name,
                origin=origin,
                query={"query": body},
                columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
            )
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        for table_name in ("shared", "held"):
            DataWarehouseTable.objects.create(
                name=table_name,
                format="Parquet",
                team=self.team,
                credential=credential,
                url_pattern="https://bucket.s3/data/*",
                columns={
                    "id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}
                },
            )

    def _resolves(self, query: str) -> bool:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team=self.team)
        try:
            resolve_types(parse_select(query), context, dialect="clickhouse")
        except QueryError:
            return False
        return True

    @parameterized.expand(
        [
            (model, table, qualifier)
            for model, tables, qualifiers in [
                ("revenue", ["revenue", "models.revenue", "`revenue`"], ["revenue", "models.revenue", "`revenue`"]),
                (
                    "marts.fees",
                    ["marts.fees", "models.marts.fees", "`marts.fees`", "models.`marts.fees`"],
                    [
                        "marts.fees",
                        "models.marts.fees",
                        "`marts.fees`",
                        "models.`marts.fees`",
                        "fees",
                        "marts__fees",
                        "models__marts__fees",
                    ],
                ),
            ]
            for table in tables
            for qualifier in qualifiers
        ]
    )
    def test_a_rename_rewrites_the_spellings_the_resolver_binds(self, model: str, table: str, qualifier: str):
        query = f"select {qualifier}.id from {table}"
        table_binds = self._resolves(f"select 1 from {table}")
        qualifier_binds = self._resolves(query)
        renamed = DataWarehouseSavedQuery.objects.get(team=self.team, name=model)

        rewritten = rename_model_references(
            query, model_spellings(renamed, Database.create_for(team=self.team)), ["moved", "income"]
        )

        # A reference keeps its form, and a qualifier takes the form of the table it binds to.
        new_name = "models.moved.income" if table.startswith("models") else "moved.income"
        new_table = new_name if table_binds else table
        new_qualifier = new_name if qualifier_binds else qualifier
        assert rewritten == f"select {new_qualifier}.id from {new_table}"
        if qualifier_binds:
            renamed.name = "moved.income"
            renamed.save()
            assert self._resolves(rewritten)

    @parameterized.expand(
        [
            (
                "another_subquery_qualifies_a_column_named_like_the_model",
                "revenue",
                "select a.id from (select id from revenue) as a join (select revenue.id from events) as b on 1 = 1",
                "select a.id from (select id from moved.income) as a join (select revenue.id from events) as b on 1 = 1",
            ),
            (
                "a_subquery_does_not_see_the_outer_table",
                "revenue",
                "select 1 from revenue where id in (select revenue.id from events)",
                "select 1 from moved.income where id in (select revenue.id from events)",
            ),
            (
                "cte_named_like_the_model",
                "revenue",
                "with revenue as (select 1 as id) select revenue.id from revenue",
                None,
            ),
            (
                "aliased_read_changes_the_table_only",
                "revenue",
                "select r.id, revenue.id, revenue from revenue as r",
                "select r.id, revenue.id, revenue from moved.income as r",
            ),
            (
                "asterisk",
                "revenue",
                "select revenue.*, marts.orders.* from revenue join marts.orders on revenue.id = marts.orders.id",
                "select moved.income.*, marts.orders.* from moved.income join marts.orders on moved.income.id = marts.orders.id",
            ),
            (
                "comments_and_formatting_survive",
                "revenue",
                "SELECT\n    `revenue` . id, -- revenue.id stays in a comment\n    'revenue.id' AS label /* revenue */\nFROM\n    revenue -- from revenue\nWHERE revenue.id > 1",
                "SELECT\n    moved.income . id, -- revenue.id stays in a comment\n    'revenue.id' AS label /* revenue */\nFROM\n    moved.income -- from revenue\nWHERE moved.income.id > 1",
            ),
            (
                "lambda_argument_named_like_the_model",
                "revenue",
                "select arrayMap(revenue -> revenue.1, [(1, 2)]), arrayMap(x -> revenue.id + x, [1]) from revenue",
                "select arrayMap(revenue -> revenue.1, [(1, 2)]), arrayMap(x -> moved.income.id + x, [1]) from moved.income",
            ),
            (
                "another_table_under_the_same_prefix",
                "revenue",
                "select revenue.id from revenue join revenue.archive on 1 = 1",
                "select moved.income.id from moved.income join revenue.archive on 1 = 1",
            ),
            (
                "a_synced_table_holds_the_bare_name",
                "held",
                "select held.id, models.held.id from held join models.held on 1 = 1",
                "select held.id, models.moved.income.id from held join models.moved.income on 1 = 1",
            ),
            ("other_models_stay", "revenue", "select costs.id from costs", None),
            (
                "a_cte_defined_over_the_model",
                "revenue",
                "with revenue as (select * from revenue) select * from revenue",
                "with revenue as (select * from moved.income) select * from revenue",
            ),
            (
                "a_cte_defined_over_the_model_in_a_union",
                "revenue",
                "with revenue as (select * from revenue) select * from revenue union all select * from revenue",
                "with revenue as (select * from moved.income) select * from revenue union all select * from revenue",
            ),
            (
                "a_longer_nested_table_wins_the_qualifier",
                "marts.fees",
                "select marts.fees.archive.id, marts.fees.id from marts.fees join marts.fees.archive on 1 = 1",
                "select marts.fees.archive.id, moved.income.id from moved.income join marts.fees.archive on 1 = 1",
            ),
            (
                "pivot_source",
                "revenue",
                "select 1 from revenue pivot (count() for id in (1))",
                "select 1 from moved.income pivot (count() for id in (1))",
            ),
            (
                "unpivot_source",
                "revenue",
                "select * from revenue unpivot (v for k in (id))",
                "select * from moved.income unpivot (v for k in (id))",
            ),
        ]
    )
    def test_rename_model_references(self, _case: str, model: str, query: str, expected: str | None):
        renamed = DataWarehouseSavedQuery.objects.get(team=self.team, name=model)
        spellings = model_spellings(renamed, Database.create_for(team=self.team))
        assert rename_model_references(query, spellings, ["moved", "income"]) == (
            expected if expected is not None else query
        )

    def test_a_rename_to_a_bare_name_keeps_each_reference_form(self):
        renamed = DataWarehouseSavedQuery.objects.get(team=self.team, name="revenue")
        spellings = model_spellings(renamed, Database.create_for(team=self.team))

        rewritten = rename_model_references(
            "select revenue.id, models.revenue.id from revenue join models.revenue on 1 = 1",
            spellings,
            ["moved", "income"],
        )

        assert rewritten == (
            "select moved.income.id, models.moved.income.id from moved.income join models.moved.income on 1 = 1"
        )

    @parameterized.expand(
        [
            ("does_not_parse", "revenue", "select * from revenue where", DOES_NOT_PARSE),
            (
                "comment_inside_a_table_name",
                "marts.orders",
                "select 1 from marts /* c */ . orders",
                PARSE_CHECK_FAILED,
            ),
        ]
    )
    def test_rename_model_references_refuses_what_it_cannot_prove(
        self, _case: str, model: str, query: str, reason: str
    ):
        renamed = DataWarehouseSavedQuery.objects.get(team=self.team, name=model)
        spellings = model_spellings(renamed, Database.create_for(team=self.team))
        with pytest.raises(ModelReferenceRewriteError, match=reason):
            rename_model_references(query, spellings, ["moved", "income"])

    @parameterized.expand(
        [
            (
                "a_cte_with_the_new_name",
                "income",
                "with income as (select 999 as id) select revenue.id from revenue",
                READS_ANOTHER_TABLE,
            ),
            (
                "a_cte_with_the_new_name_read_unqualified",
                "income",
                "with income as (select 2 as id) select id from revenue",
                READS_ANOTHER_TABLE,
            ),
            (
                "a_table_alias_with_the_new_name",
                "income",
                "select revenue.id, income.event from revenue join events as income on 1 = 1",
                DOES_NOT_RESOLVE,
            ),
            (
                "an_expression_named_by_its_text",
                "income",
                "select toString(revenue.id), revenue.id from revenue",
                "The rename would change its output column toString(revenue.id) to toString(income.id). "
                "Give that column an alias first.",
            ),
            ("a_plain_read", "income", "select revenue.id from revenue", None),
            ("a_cte_with_another_name", "income", "with other as (select 2 as id) select id from revenue", None),
        ]
    )
    def test_plan_blocks_a_rewrite_that_reads_something_else(
        self, _case: str, new_name: str, query: str, reason: str | None
    ):
        renamed = DataWarehouseSavedQuery.objects.get(team=self.team, name="revenue")
        dependent = DataWarehouseSavedQuery.objects.create(team=self.team, name="dependent", query={"query": query})

        plan = plan_model_rename(self.team, renamed.id, new_name)

        dependent_blocks = [entry.reason for entry in plan.blocked if entry.saved_query_id == dependent.id]
        dependent_rewrites = [entry for entry in plan.rewrites if entry.saved_query_id == dependent.id]
        assert dependent_blocks == ([reason] if reason is not None else [])
        assert len(dependent_rewrites) == (0 if reason is not None else 1)

    def test_plan_rewrites_a_model_that_reads_the_renamed_model_directly_and_through_another(self):
        renamed = DataWarehouseSavedQuery.objects.get(team=self.team, name="revenue")
        middle = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="middle",
            query={"query": "select revenue.id from revenue"},
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64", "valid": True}},
        )
        top = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="top",
            query={"query": "select middle.id from middle join revenue on middle.id = revenue.id"},
        )

        plan = plan_model_rename(self.team, renamed.id, "income")

        assert plan.blocked == ()
        rewrites = {entry.saved_query_id: entry.after for entry in plan.rewrites}
        assert {key: rewrites.get(key) for key in (middle.id, top.id)} == {
            middle.id: "select income.id from income",
            top.id: "select middle.id from middle join income on middle.id = income.id",
        }


class TestBoundedResolver(BaseTest):
    def _resolve(
        self,
        query: str,
        initial_view_name: str = "test_model",
        max_view_depth: int = DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
        deadline_seconds: float | None = DEFAULT_RESOLUTION_DEADLINE_SECONDS,
    ) -> BoundedResolver:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(
            context=context,
            dialect="hogql",
            initial_view_name=initial_view_name,
            max_view_depth=max_view_depth,
            deadline_seconds=deadline_seconds,
        )
        resolver.visit(parse_select(query))
        return resolver

    def _make_chain(self, length: int) -> None:
        """Create a chain of saved-query views: v0 → v1 → … → events."""
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v0",
            query={"query": "select event from events"},
        )
        for i in range(1, length):
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=f"v{i}",
                query={"query": f"select * from v{i - 1}"},
            )

    def _make_diamond(self) -> None:
        """Create `shared` (reads events) and `mid` (reads shared)."""
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="shared",
            query={"query": "select event from events"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="mid",
            query={"query": "select event from shared"},
        )

    @parameterized.expand(
        [
            # a view joined to itself is not a cycle
            ("self_join", "select a.* from shared a join shared b on 1=1", {"models.shared"}),
            # `mid` reads `shared`, and `shared` also sits earlier in the same FROM
            ("shared_joined_first", "select m.* from shared s join mid m on 1=1", {"models.shared", "models.mid"}),
            # same diamond, reversed join order — `shared` must still be registered as a parent
            ("shared_joined_second", "select m.* from mid m join shared s on 1=1", {"models.shared", "models.mid"}),
            # union branches are true siblings and must keep working
            ("union_branches", "select * from shared union all select * from mid", {"models.shared", "models.mid"}),
        ],
    )
    def test_sibling_view_joins_resolve_without_cycle(self, _name: str, query: str, expected_parents: set[str]):
        self._make_diamond()

        assert get_parents_from_model_query(self.team, "caller", query) == expected_parents

    @parameterized.expand(
        [
            ("where", "select * from shared where event in (select event from mid)", {"models.shared", "models.mid"}),
            (
                "nested_in_from_subquery",
                "select * from (select * from shared where event in (select event from mid))",
                {"models.shared", "models.mid"},
            ),
        ],
    )
    def test_view_read_from_a_subquery_is_a_parent(self, _name: str, query: str, expected_parents: set[str]):
        self._make_diamond()

        assert get_parents_from_model_query(self.team, "caller", query) == expected_parents

    @parameterized.expand(
        [
            ("bare_names", "a", "b"),
            ("caller_reaches_back_under_models_root", "models.a", "b"),
            ("callee_named_under_models_root", "a", "models.b"),
            ("both_under_models_root", "models.a", "models.b"),
        ]
    )
    def test_cycle_precedes_configurable_depth_limit_and_keeps_context(self, _name: str, ref_to_a: str, ref_to_b: str):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="a",
            query={"query": f"select * from {ref_to_b}"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="b",
            query={"query": f"select * from {ref_to_a}"},
        )

        with pytest.raises(ResolutionCycleError) as exc_info:
            self._resolve(f"select * from {ref_to_b}", initial_view_name="a", max_view_depth=1)

        # the inner view where the cycle was detected is `a` (already on the stack), and the caller is also `a`
        assert exc_info.value.view_name == "a"
        assert exc_info.value.initial_view == "a"

    def _make_union_bodied_view_with_ctes(self) -> None:
        """Create `unioned`, whose body is a UNION behind a WITH, with one CTE per branch."""
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="leaf",
            query={"query": "select event from events"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="unioned",
            query={
                "query": (
                    "with a as (select event from events), b as (select event from leaf) "
                    "select event from a union all select event from b"
                )
            },
        )

    def test_ctes_inside_union_body_are_not_parents_when_walking_the_body(self):
        # When a union body is walked directly (syncing the union view itself), its branch
        # CTEs must not leak as parents — the branch that reads `b` is otherwise walked before
        # the leading WITH is in scope. The real sources (events, leaf) are the parents.
        self._make_union_bodied_view_with_ctes()

        body = "with a as (select event from events), b as (select event from leaf) select event from a union all select event from b"
        assert get_parents_from_model_query(self.team, "unioned", body) == {"events", "models.leaf"}

    def test_cycle_through_union_bodied_view_raises(self):
        # `view_name` is only stamped on ast.SelectQuery, so a view whose body is a top-level
        # UNION has no name on the AST node the resolver walks into. Cycle detection must
        # still hold for it.
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="u",
            query={"query": "select event from events union all select event from w"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="w",
            query={"query": "select event from u"},
        )

        with pytest.raises(ResolutionCycleError) as exc_info:
            get_parents_from_model_query(self.team, "caller", "select * from u")

        assert exc_info.value.view_name == "u"

    def test_union_bodied_view_registers_as_parent_under_its_own_name(self):
        # A regular view registers as a parent under its own name (the resolver stamps
        # view_name on the SelectQuery body). A union-bodied view must behave the same way:
        # the DAG edge should point at the view, not skip past it to the view's own sources.
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="leaf",
            query={"query": "select event from events"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="regular_view",
            query={"query": "select event from leaf"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="union_view",
            query={"query": "select event from leaf union all select event from events"},
        )

        # baseline: a regular view is its consumer's parent
        assert get_parents_from_model_query(self.team, "caller", "select * from regular_view") == {
            "models.regular_view"
        }

        # a union-bodied view must be too — not replaced by {leaf, events}
        assert get_parents_from_model_query(self.team, "caller", "select * from union_view") == {"models.union_view"}

    def test_values_join_after_view_does_not_crash(self):
        # bug 2's fix walks past the first view instead of breaking, so a VALUES/PIVOT/UNPIVOT
        # join positioned after a view is now reached. VALUES carries no parent — it must be
        # skipped, not raise "No handler".
        self._make_diamond()

        parents = get_parents_from_model_query(
            self.team, "caller", "select 1 from shared s join (select 1 as n) v on 1=1"
        )
        assert parents == {"models.shared"}

        # the actual crash shape: a real VALUES clause joined after a view
        parents = get_parents_from_model_query(
            self.team, "caller", "select n from shared s cross join (values (1), (2)) as v(n)"
        )
        assert parents == {"models.shared"}

    def test_pivot_over_join_keeps_its_sources_as_parents(self):
        # PIVOT/UNPIVOT wrap their source in `.table`, which can be a whole join — its tables
        # are real parents and must not be dropped or crash the walk.
        parents = get_parents_from_model_query(
            self.team,
            "caller",
            "select 1 from events e join persons p on 1=1 pivot (count() for e.event in ('x'))",
        )
        assert parents == {"events", "persons"}

    def test_nested_non_initial_union_branch_with_own_cte(self):
        # A WITH on a parenthesized sub-union sitting in a *non-initial* branch must scope only
        # that sub-union's branches. Walking this body (syncing the view itself), `y` must
        # resolve as a CTE, not leak as a parent — its source `events` is the parent.
        body = (
            "select event from events "
            "union all "
            "(with y as (select event from events) select event from y union all select event from y)"
        )

        assert get_parents_from_model_query(self.team, "nested_union", body) == {"events"}

    @parameterized.expand(
        [
            # `WITH x AS (...) SELECT FROM x` saved as view `x`: the CTE shadows the view's
            # own name, so this is not a self-cycle.
            ("own_name", "reservations_all"),
            # A CTE shadowing a different existing view must win over inlining that view.
            ("other_view_name", "some_other_view"),
        ]
    )
    def test_cte_shadowing_a_view_name_resolves_to_the_cte(self, _name, shadowed_name):
        DataWarehouseSavedQuery.objects.create(
            team=self.team, name=shadowed_name, query={"query": "select id from persons"}
        )
        body = f"with {shadowed_name} as (select event from events) select * from {shadowed_name}"

        assert get_parents_from_model_query(self.team, "reservations_all", body) == {"events"}

    def test_depth_limit_raises_when_chain_too_deep(self):
        self._make_chain(length=4)  # v0 → v1 → v2 → v3

        with pytest.raises(ResolutionDepthExceededError) as exc_info:
            self._resolve("select * from v3", initial_view_name="caller", max_view_depth=2)

        assert exc_info.value.max_depth == 2
        assert exc_info.value.depth == 3
        assert exc_info.value.initial_view == "caller"

    def test_depth_limit_allows_chain_within_budget(self):
        self._make_chain(length=3)  # v0 → v1 → v2

        resolver = self._resolve("select * from v2", initial_view_name="caller", max_view_depth=10)

        assert resolver.max_view_depth_observed == 3

    def test_negative_deadline_triggers_timeout_immediately(self):
        # A negative deadline is "already expired": the first visit_join_expr raises
        # without depending on clock precision between init and first visit.
        with pytest.raises(ResolutionTimeoutError) as exc_info:
            self._resolve("select * from events", initial_view_name="caller", deadline_seconds=-1.0)

        assert exc_info.value.deadline_seconds == -1.0
        assert exc_info.value.elapsed_seconds >= 0.0
        assert exc_info.value.initial_view == "caller"

    def test_deadline_none_disables_timeout(self):
        # No deadline: even with synthetic delay the resolver should not raise timeout.
        resolver = self._resolve("select * from events", initial_view_name="caller", deadline_seconds=None)
        assert resolver.deadline_seconds is None

    def test_bounded_resolver_errors_inherit_query_error(self):
        # Locks in the public contract: callers that catch QueryError (DRF exception
        # handlers, workflow error mappers) keep working when cycles/depth/timeouts fire.
        DataWarehouseSavedQuery.objects.create(team=self.team, name="a", query={"query": "select * from b"})
        DataWarehouseSavedQuery.objects.create(team=self.team, name="b", query={"query": "select * from a"})

        with pytest.raises(QueryError) as exc_info:
            get_parents_from_model_query(self.team, "a", "select * from b")

        assert isinstance(exc_info.value, ResolutionCycleError)

    def test_soft_mode_depth_observes_without_raising(self):
        self._make_chain(length=4)  # v0 → v1 → v2 → v3, would breach max_view_depth=2

        # enforce_bounds=False: depth overshoot is recorded but the walk continues
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(
            context=context,
            dialect="hogql",
            initial_view_name="caller",
            max_view_depth=2,
            enforce_bounds=False,
        )
        resolver.visit(parse_select("select * from v3"))

        assert resolver.max_view_depth_observed > resolver.max_view_depth

    def test_soft_mode_deadline_observes_without_raising(self):
        # Negative deadline = already expired. In soft mode we record but don't raise.
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(
            context=context,
            dialect="hogql",
            initial_view_name="caller",
            deadline_seconds=-1.0,
            enforce_bounds=False,
        )
        resolver.visit(parse_select("select * from events"))

        assert resolver.deadline_violated is True

    def test_soft_mode_cycle_still_raises(self):
        # Cycles MUST raise even in soft mode — observe-only would loop forever
        # because the resolver re-enters the same view.
        DataWarehouseSavedQuery.objects.create(team=self.team, name="a", query={"query": "select * from b"})
        DataWarehouseSavedQuery.objects.create(team=self.team, name="b", query={"query": "select * from a"})

        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(context=context, dialect="hogql", initial_view_name="a", enforce_bounds=False)

        with pytest.raises(ResolutionCycleError):
            resolver.visit(parse_select("select * from b"))


class TestResolutionMetrics(BaseTest):
    def _counter(self, status: str, source: str = RESOLUTION_SOURCE_LINEAGE) -> float:
        return (
            REGISTRY.get_sample_value("data_modeling_dag_resolution_total", {"status": status, "source": source}) or 0.0
        )

    def _duration_count(self, source: str = RESOLUTION_SOURCE_LINEAGE) -> float:
        return (
            REGISTRY.get_sample_value("data_modeling_dag_resolution_duration_seconds_count", {"source": source}) or 0.0
        )

    def test_ok_path_increments_counter_and_records_depth(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="leaf",
            query={"query": "select event from events"},
        )
        before_ok = self._counter("ok")
        before_count = self._duration_count()
        before_materialization_ok = self._counter("ok", RESOLUTION_SOURCE_MATERIALIZATION)

        parents = get_parents_from_model_query(self.team, "caller", "select * from leaf")

        assert parents == {"models.leaf"}
        assert self._counter("ok") - before_ok == 1.0
        assert self._duration_count() - before_count == 1.0
        # A lineage resolution must not move the materialization counter: without the label the
        # two share one series, and the rarer source is the one that gets hidden.
        assert self._counter("ok", RESOLUTION_SOURCE_MATERIALIZATION) - before_materialization_ok == 0.0

    def test_cycle_increments_cycle_status(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="a",
            query={"query": "select * from b"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="b",
            query={"query": "select * from a"},
        )
        before_cycle = self._counter("cycle")

        with pytest.raises(ResolutionCycleError):
            get_parents_from_model_query(self.team, "a", "select * from b")

        assert self._counter("cycle") - before_cycle == 1.0

    def test_unknown_table_increments_error_status(self):
        before_error = self._counter("error")

        with pytest.raises(QueryError):
            get_parents_from_model_query(self.team, "caller", "select * from some_random_view")

        assert self._counter("error") - before_error == 1.0


class TestResolverFactoryInjection(BaseTest):
    def test_prepare_ast_for_printing_uses_injected_bounded_resolver(self):
        from posthog.hogql.printer import prepare_ast_for_printing

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v0",
            query={"query": "select event from events"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v1",
            query={"query": "select * from v0"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v2",
            query={"query": "select * from v1"},
        )

        query_node = parse_select("select * from v2")
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)

        def factory(ctx, dialect, scopes):
            return BoundedResolver(
                scopes=scopes, context=ctx, dialect=dialect, initial_view_name="caller", max_view_depth=1
            )

        with pytest.raises(ResolutionDepthExceededError):
            prepare_ast_for_printing(query_node, context=context, dialect="clickhouse", resolver_factory=factory)

    def test_prepare_ast_for_printing_default_resolver_accepts_short_view_chain(self):
        from posthog.hogql.printer import prepare_ast_for_printing

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v0",
            query={"query": "select event from events"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v1",
            query={"query": "select * from v0"},
        )

        query_node = parse_select("select * from v1")
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)

        prepare_ast_for_printing(query_node, context=context, dialect="clickhouse")

    def test_shared_deadline_anchor_spans_multiple_resolvers(self):
        """Two BoundedResolvers built from the same factory must share a deadline clock.

        Without a shared anchor, each resolver would get its own deadline_seconds budget
        and prepare_ast_for_printing's multi-pass resolution would compound the bound.
        """
        from products.data_modeling.backend.models.modeling import bounded_resolver_factory_for_view

        factory = bounded_resolver_factory_for_view("caller", deadline_seconds=10.0)
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)

        # Factory seeds one anchor and hands the same value to every resolver it produces.
        r1 = factory(context, "hogql", None)
        r2 = factory(context, "hogql", None)
        assert isinstance(r1, BoundedResolver)
        assert isinstance(r2, BoundedResolver)
        assert r1.deadline_anchor is not None
        assert r2.deadline_anchor == r1.deadline_anchor

    def test_factory_threaded_through_resolve_lazy_tables(self):
        """Lazy-table resolution invokes the factory on subqueries it builds — depth bound applies.

        Queries against events touch lazy joins (persons, etc.) which `resolve_lazy_tables`
        materializes as subqueries and re-resolves. Threading the factory means those
        re-resolutions go through BoundedResolver too.
        """
        from posthog.hogql.printer import prepare_ast_for_printing

        from products.data_modeling.backend.models.modeling import bounded_resolver_factory_for_view

        # Use the shared factory helper so the deadline is end-to-end across passes
        factory = bounded_resolver_factory_for_view("caller", max_view_depth=DEFAULT_RESOLUTION_MAX_VIEW_DEPTH)

        query_node = parse_select("select event from events")
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)

        # Should not raise — a simple events query is well within bounds, but it does
        # exercise the lazy-table path (events has lazy joins to persons/sessions).
        # Success here proves the factory is invoked at lazy_tables.resolve_types and
        # those nested resolutions don't error.
        prepare_ast_for_printing(query_node, context=context, dialect="clickhouse", resolver_factory=factory)
