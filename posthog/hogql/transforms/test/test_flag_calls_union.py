import re
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from posthog.test.base import (
    APIBaseTest,
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import param, parameterized

from posthog.schema import (
    HogQLQueryModifiers,
    InCohortVia,
    InlineCohortCalculation,
    MaterializationMode,
    PersonsOnEventsMode,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.database.models import DatabaseField, FieldTraverser, LazyJoin, StringJSONDatabaseField, VirtualTable
from posthog.hogql.database.schema.flag_evaluations import FLAG_EVALUATIONS_COMPLETE_DAYS
from posthog.hogql.database.schema.util.where_clause_extractor import is_nondeterministic_function
from posthog.hogql.errors import QueryError
from posthog.hogql.functions.mapping import HOGQL_CLICKHOUSE_FUNCTIONS
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import HogQLQueryExecutor, execute_hogql_query
from posthog.hogql.test.test_prompt_jev import gateway_response
from posthog.hogql.transforms.flag_calls_union import rename_flag_call_scans_to_union
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.escape import substitute_params
from posthog.clickhouse.query_tagging import get_query_tags
from posthog.constants import AvailableFeature
from posthog.test.persons import create_group_type_mapping

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.cohorts.backend.models.cohort import Cohort
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

from ee.clickhouse.materialized_columns.columns import materialize

MIXED = "event IN ('$pageview', '$feature_flag_called')"
SESSION_ID = "0190a8d1-3f7a-7b00-8000-000000000001"
E_MIXED = "e.event IN ('$pageview', '$feature_flag_called')"
UNION = "posthog.events_with_flag_calls"
EVENTS = FlagEvaluationsMode.EVENTS
READ = FlagEvaluationsMode.READ_FLAG_EVALUATIONS
ONLY = FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY


UNION_EXPANSION = "FROM flag_evaluations"
FLAG_CALLS_FROM = "FROM events WHERE event = '$feature_flag_called'"
FLAG_CALLS = f"SELECT count() {FLAG_CALLS_FROM}"
SAMPLED_FLAG_CALLS = "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$feature_flag_called'"
KEYED_BOUNDED_FLAG_CALLS = f"{FLAG_CALLS} AND properties.$feature_flag = 'f' AND timestamp >= now() - INTERVAL 7 DAY"


def _performed_flag_call_cohort(team, flag_key: str) -> Cohort:
    return Cohort.objects.create(
        team=team,
        name=f"called {flag_key}",
        filters={
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "$feature_flag_called",
                                "type": "behavioral",
                                "value": "performed_event",
                                "event_type": "events",
                                "time_value": 30,
                                "time_interval": "day",
                                "event_filters": [
                                    {"key": "$feature_flag", "type": "event", "value": flag_key, "operator": "exact"}
                                ],
                            }
                        ],
                    }
                ],
            }
        },
    )


class _TableCollector(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[str] = []

    def visit_join_expr(self, node: ast.JoinExpr) -> None:
        if isinstance(node.table, ast.Field):
            self.tables.append(".".join(str(part) for part in node.table.chain))
        super().visit_join_expr(node)


def _select(query: str | ast.SelectQuery) -> ast.SelectQuery:
    return cast(ast.SelectQuery, parse_select(query) if isinstance(query, str) else clone_expr(query))


def _global_join(query: str) -> ast.SelectQuery:
    # HogQL has no GLOBAL syntax. The recordings list builds a GLOBAL join in its AST.
    select = _select(query)
    assert select.select_from is not None and select.select_from.next_join is not None
    select.select_from.next_join.join_type = "GLOBAL INNER JOIN"
    return select


def _alias_flood() -> ast.SelectQuery:
    # Work that grows with the square of the alias count turns this case into a hang.
    select = _select(f"SELECT 1 FROM events WHERE {MIXED}")
    aliases = ast.Tuple(exprs=[ast.Alias(alias=f"a{n}", expr=ast.Constant(value=n)) for n in range(150_000)])
    select.select.append(
        ast.Call(name="arrayMap", args=[ast.Lambda(args=["x"], expr=aliases), ast.Array(exprs=[ast.Constant(value=1)])])
    )
    return select


def _alias_chain_read_many_times() -> ast.SelectQuery:
    # `event AS a0, a0 AS a1, ...` read thousands of times in one IN list.
    select = _select("SELECT 1 FROM events")
    select.select = [
        ast.Alias(alias=f"a{n}", expr=ast.Field(chain=[f"a{n - 1}" if n else "event"])) for n in range(10_000)
    ]
    reads: list[ast.Expr] = [ast.Field(chain=["a9999"]) for _ in range(10_000)]
    select.where = ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[*reads, ast.Constant(value="$pageview"), ast.Constant(value="$feature_flag_called")]),
    )
    return select


def _lambdas_inside_a_lambda_with_many_aliases() -> ast.SelectQuery:
    select = _select(f"SELECT 1 FROM events WHERE {MIXED}")
    body: list[ast.Expr] = [ast.Alias(alias=f"a{n}", expr=ast.Constant(value=n)) for n in range(40_000)]
    body += [ast.Lambda(args=["y"], expr=ast.Constant(value=1)) for _ in range(40_000)]
    select.select.append(
        ast.Call(
            name="arrayMap",
            args=[ast.Lambda(args=["x"], expr=ast.Tuple(exprs=body)), ast.Array(exprs=[ast.Constant(value=1)])],
        )
    )
    return select


def _list_alias_read_many_times() -> ast.SelectQuery:
    select = _select("SELECT 1 FROM events")
    names = ast.Tuple(exprs=[*(ast.Constant(value=f"e{n}") for n in range(10_000)), ast.Constant(value="$pageview")])
    select.select = [ast.Alias(alias="names", expr=names)]
    select.where = ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(
            exprs=[*(ast.Field(chain=["names"]) for _ in range(10_000)), ast.Constant(value="$feature_flag_called")]
        ),
    )
    return select


def _list_alias_in_many_comparisons() -> ast.SelectQuery:
    select = _select(f"SELECT 1 FROM events WHERE {MIXED}")
    names = ast.Tuple(exprs=[ast.Constant(value=f"e{n}") for n in range(10_000)])
    comparisons: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.In, left=ast.Field(chain=["event"]), right=ast.Field(chain=["names"])
        )
        for _ in range(10_000)
    ]
    select.select = [ast.Alias(alias="names", expr=names), *comparisons]
    return select


def _with_list_read_by_many_subqueries() -> ast.SelectQuery:
    names = ast.Tuple(
        exprs=[
            *(ast.Constant(value="$feature_flag_called", start=n, end=n + 1) for n in range(30_000)),
            ast.Constant(value="$pageview"),
        ]
    )
    branches = [_select("SELECT 1 FROM events WHERE event IN names") for _ in range(300)]
    select = _select("SELECT 1 FROM (SELECT 1)")
    select.ctes = {"names": ast.CTE(name="names", expr=names, cte_type="column")}
    assert select.select_from is not None
    select.select_from.table = ast.SelectSetQuery(
        initial_select_query=branches[0],
        subsequent_select_queries=[
            ast.SelectSetNode(set_operator="UNION ALL", select_query=branch) for branch in branches[1:]
        ],
    )
    return select


def _long_with() -> ast.SelectQuery:
    select = _select("SELECT 1 FROM events WHERE event IN ('$pageview', c49999)")
    names = [*(f"e{n}" for n in range(49_999)), "$feature_flag_called"]
    select.ctes = {
        f"c{n}": ast.CTE(name=f"c{n}", expr=ast.Constant(value=name), cte_type="column") for n, name in enumerate(names)
    }
    return select


def _set_mode(organization, mode: FlagEvaluationsMode) -> None:
    OrganizationFeatureFlagsConfig.objects.update_or_create(
        organization=organization, defaults={"flag_evaluations_mode": mode}
    )


def _enabled_flags(union: bool):
    enabled = {"hogql-flag-calls-union"} if union else set()
    return patch(
        "posthog.hogql.database.database.feature_enabled_or_false",
        side_effect=lambda key, *args, **kwargs: key in enabled,
    )


def _flag_evaluations_table_in_catalog():
    # Outside Cloud and DEBUG the catalog leaves the table out for an organization on mode 0.
    return patch("products.feature_flags.backend.facade.flags.is_flag_evaluations_table_enabled", return_value=True)


def _restrict(organization, team, name: str) -> None:
    organization.available_product_features = [
        {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
    ]
    organization.save()
    definition = PropertyDefinition.objects.create(
        team=team, name=name, property_type="String", type=PropertyDefinition.Type.EVENT
    )
    PropertyAccessControl.objects.create(
        team=team, property_definition=definition, access_level=PropertyAccessLevel.NONE.value
    )


class TestRenameFlagCallScansToUnion(SimpleTestCase):
    @parameterized.expand(
        [
            ("event_in_a_list_with_other_events", f"SELECT count() FROM events WHERE {MIXED}", [UNION], []),
            ("paths_v2_step_sources", f"SELECT e.event FROM events AS e WHERE {E_MIXED}", [UNION], []),
            (
                "funnel_step_column",
                "SELECT if(event = '$feature_flag_called' AND properties.$feature_flag = 'f', 1, 0) AS step_1 "
                "FROM events",
                [UNION],
                [],
            ),
            (
                "or_of_event_comparisons",
                "SELECT count() FROM events WHERE event = '$pageview' OR equals(event, '$feature_flag_called')",
                [UNION],
                [],
            ),
            # The flag_evaluations swap handles this scan. Events holds every flag call on mode 1. The swap swaps or
            # refuses the scan on mode 2.
            ("only_flag_calls", "SELECT count() FROM events WHERE event = '$feature_flag_called'", ["events"], []),
            param(
                "only_flag_calls_with_sample_on_mode_1",
                "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$feature_flag_called'",
                ["events"],
                [],
                False,
            ),
            # Phase 1 cannot swap a sampled scan, and the union applies the ratio.
            (
                "only_flag_calls_with_sample_on_mode_2",
                "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$feature_flag_called'",
                [UNION],
                [],
            ),
            (
                "only_flag_calls_with_sample_on_posthog_events_on_mode_2",
                "SELECT count() FROM posthog.events SAMPLE 0.1 WHERE event = '$feature_flag_called'",
                [UNION],
                [],
            ),
            (
                "left_join_after_the_scan",
                f"SELECT count() FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                [UNION, "persons"],
                [],
            ),
            (
                "left_join_with_an_unqualified_event",
                f"SELECT count() FROM events LEFT JOIN persons AS p ON events.person_id = p.id WHERE {MIXED}",
                [UNION, "persons"],
                [],
            ),
            (
                "left_join_with_an_unqualified_event_aliased_to_itself",
                "SELECT event AS event, count() FROM events LEFT JOIN persons AS p ON events.person_id = p.id "
                f"WHERE {MIXED} GROUP BY event",
                [UNION, "persons"],
                [],
            ),
            (
                "only_flag_calls_with_a_join_and_an_unqualified_event",
                "SELECT count() FROM events LEFT JOIN persons AS p ON events.person_id = p.id "
                "WHERE event = '$feature_flag_called'",
                ["events", "persons"],
                [],
            ),
            (
                "array_join_with_an_unqualified_event",
                f"SELECT count() FROM events ARRAY JOIN [1, 2] AS x WHERE {MIXED}",
                [UNION],
                [],
            ),
            (
                "inner_join_after_the_scan",
                f"SELECT count() FROM events AS e INNER JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                [UNION, "persons"],
                [],
            ),
            (
                "global_join_after_the_scan",
                _global_join(
                    f"SELECT count() FROM events AS e INNER JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}"
                ),
                [UNION, "persons"],
                [],
            ),
            ("qualified_events_name", f"SELECT count() FROM posthog.events WHERE {MIXED}", [UNION], []),
            ("sample_one", f"SELECT count() FROM events SAMPLE 1 WHERE {MIXED}", [UNION], []),
            ("scan_in_a_subquery", f"SELECT count() FROM (SELECT event FROM events WHERE {MIXED})", [UNION], []),
            (
                "comparison_only_in_a_subquery",
                f"SELECT count() FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE {MIXED})",
                ["events", UNION],
                [],
            ),
            (
                "no_flag_call_comparison",
                "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$pageview'",
                ["events"],
                [],
            ),
            ("not_equals", "SELECT count() FROM events WHERE event != '$feature_flag_called'", ["events"], []),
            (
                "constant_on_another_column",
                "SELECT count() FROM events WHERE distinct_id = '$feature_flag_called'",
                ["events"],
                [],
            ),
            (
                "scan_after_another_table",
                f"SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id WHERE {E_MIXED}",
                ["persons", "events"],
                ["it joins events after another table"],
            ),
            (
                "scan_of_only_flag_calls_after_another_table",
                "SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id "
                "WHERE e.event = '$feature_flag_called'",
                ["persons", "events"],
                ["it joins events after another table"],
            ),
            (
                "alias_of_event_in_a_list_with_other_events",
                "SELECT event AS name, count() FROM events "
                "WHERE name IN ('$pageview', '$feature_flag_called') GROUP BY name",
                [UNION],
                [],
            ),
            (
                "alias_of_an_alias_of_event",
                "SELECT event AS a, a AS b FROM events WHERE b IN ('$pageview', '$feature_flag_called')",
                [UNION],
                [],
            ),
            # Substituting each alias of a call in place would copy about 2**40 nodes, so a regression hangs here.
            (
                "long_chain_of_aliases_that_each_name_the_one_before_twice",
                "SELECT event AS a0, "
                + ", ".join(f"concat(a{n - 1}, a{n - 1}) AS a{n}" for n in range(1, 41))
                + f" FROM events WHERE a40 = '' AND {MIXED}",
                [UNION],
                [],
            ),
            (
                "alias_of_a_comparison_with_flag_calls",
                "SELECT event = '$feature_flag_called' AS is_flag_call, count() FROM events "
                "WHERE is_flag_call GROUP BY is_flag_call",
                [UNION],
                [],
            ),
            (
                "alias_of_the_flag_call_event_name",
                "SELECT '$feature_flag_called' AS name, count() FROM events WHERE event = name",
                [UNION],
                [],
            ),
            (
                "alias_of_a_comparison_in_the_filter",
                "SELECT count() FROM events WHERE (event = '$feature_flag_called' AS is_flag_call)",
                [UNION],
                [],
            ),
            (
                "inline_alias_of_event_pinned_to_only_flag_calls",
                "SELECT count() FROM events WHERE (event AS name) = '$feature_flag_called'",
                ["events"],
                [],
            ),
            (
                "alias_of_a_column_that_a_later_alias_shadows",
                "SELECT distinct_id AS d, event AS distinct_id FROM events "
                f"WHERE d = '$feature_flag_called' AND {MIXED}",
                [UNION],
                [],
            ),
            (
                "lambda_argument_named_like_an_alias_of_event",
                "SELECT e.event AS name FROM persons AS p JOIN events AS e ON p.id = e.person_id "
                "WHERE arrayExists(name -> name = '$feature_flag_called', ['$feature_flag_called'])",
                ["persons", "events"],
                [],
            ),
            (
                "alias_inside_a_lambda_shadowing_an_alias_of_event_after_another_table",
                "SELECT e.event AS name, arrayMap(x -> ((x AS name), name = '$feature_flag_called'), ['$pageview']) "
                "FROM persons AS p JOIN events AS e ON p.id = e.person_id",
                ["persons", "events"],
                [],
            ),
            ("many_aliases_inside_one_lambda", _alias_flood(), [UNION], []),
            ("long_alias_chain_read_many_times", _alias_chain_read_many_times(), [UNION], []),
            ("list_alias_read_many_times", _list_alias_read_many_times(), [UNION], []),
            ("list_alias_in_many_comparisons", _list_alias_in_many_comparisons(), [UNION], []),
            (
                "many_lambdas_inside_a_lambda_with_many_aliases",
                _lambdas_inside_a_lambda_with_many_aliases(),
                [UNION],
                [],
            ),
            (
                "alias_of_event_inside_a_lambda",
                "SELECT count() FROM events "
                "WHERE arrayExists(x -> ((event AS ev), ev IN ('$pageview', '$feature_flag_called')).2, [1])",
                [UNION],
                [],
            ),
            (
                "alias_inside_a_lambda_of_an_alias_of_event",
                "SELECT event AS e, arrayMap(x -> ((e AS ev), ev = '$feature_flag_called'), [1]) AS m FROM events",
                [UNION],
                [],
            ),
            (
                "alias_inside_a_lambda_named_like_an_alias_of_event",
                "SELECT arrayMap(x -> (x AS a), [1]) AS m, event AS a FROM events "
                "WHERE a IN ('$pageview', '$feature_flag_called')",
                [UNION],
                [],
            ),
            (
                "alias_of_event_after_an_alias_name_repeated_in_lambdas",
                "SELECT arrayMap(x -> (x AS d), [1]) AS m, arrayMap(y -> (y AS d), [1]) AS n, event AS e FROM events "
                "WHERE e IN ('$pageview', '$feature_flag_called')",
                [UNION],
                [],
            ),
            (
                "alias_of_event_pinned_to_only_flag_calls",
                "SELECT event AS name FROM events WHERE name = '$feature_flag_called'",
                ["events"],
                [],
            ),
            (
                "alias_of_event_after_another_table",
                "SELECT e.event AS name FROM persons AS p JOIN events AS e ON p.id = e.person_id "
                "WHERE name IN ('$pageview', '$feature_flag_called')",
                ["persons", "events"],
                ["it joins events after another table"],
            ),
            (
                "inline_alias_of_event",
                "SELECT count() FROM events WHERE (event AS name) IN ('$pageview', '$feature_flag_called')",
                [UNION],
                [],
            ),
            (
                "inline_alias_of_the_flag_call_event_name",
                "SELECT count() FROM events WHERE event IN ('$pageview', ('$feature_flag_called' AS name))",
                [UNION],
                [],
            ),
            (
                "alias_of_a_tuple_with_flag_calls",
                "SELECT ('$pageview', '$feature_flag_called') AS names, count() FROM events "
                "WHERE event IN names GROUP BY names",
                [UNION],
                [],
            ),
            (
                "with_constant_in_a_list_with_other_events",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events WHERE event IN ('$pageview', fc)",
                [UNION],
                [],
            ),
            # The flag_evaluations swap does not read a WITH constant, so it cannot take this scan on mode 2.
            (
                "with_constant_pinned_to_only_flag_calls",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events WHERE event = fc",
                [UNION],
                [],
            ),
            (
                "with_tuple_as_the_in_list",
                "WITH ('$pageview', '$feature_flag_called') AS names SELECT count() FROM events WHERE event IN names",
                [UNION],
                [],
            ),
            (
                "alias_of_a_with_constant",
                "WITH '$feature_flag_called' AS fc SELECT fc AS name, count() FROM events "
                "WHERE event IN ('$pageview', name) GROUP BY name",
                [UNION],
                [],
            ),
            (
                "with_constant_inside_a_lambda",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events "
                "WHERE arrayExists(x -> event IN ('$pageview', fc), [1])",
                [UNION],
                [],
            ),
            (
                "with_constant_named_by_another_with_name",
                "WITH '$feature_flag_called' AS a, a AS b SELECT count() FROM events WHERE event IN ('$pageview', b)",
                [UNION],
                [],
            ),
            (
                "with_tuple_that_names_another_with_name",
                "WITH '$feature_flag_called' AS a, ('$pageview', a) AS names "
                "SELECT count() FROM events WHERE event IN names",
                [UNION],
                [],
            ),
            (
                "with_name_compared_with_a_lambda_argument_named_event",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events SAMPLE 0.1 "
                "WHERE event = '$pageview' AND arrayExists(event -> event = fc, ['$pageview'])",
                ["events"],
                [],
            ),
            (
                "with_value_computed_from_another_with_name",
                "WITH '$feature_flag_called' AS a, concat(a, '') AS fc "
                "SELECT count() FROM events WHERE event IN ('$pageview', fc)",
                [UNION],
                [],
            ),
            (
                "with_name_shadowed_by_an_events_column",
                "WITH '$feature_flag_called' AS distinct_id SELECT count() FROM events "
                "WHERE event IN ('$pageview', distinct_id)",
                ["events"],
                [],
            ),
            (
                "with_name_shadowed_by_a_lambda_argument",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events "
                "WHERE arrayExists(fc -> event IN ('$pageview', fc), ['$autocapture'])",
                ["events"],
                [],
            ),
            (
                "outer_with_constant_in_a_subquery",
                "WITH '$feature_flag_called' AS fc "
                "SELECT count() FROM (SELECT event FROM events WHERE event IN ('$pageview', fc))",
                [UNION],
                [],
            ),
            (
                "subquery_with_constant",
                "SELECT count() FROM "
                "(WITH '$feature_flag_called' AS fc SELECT event FROM events WHERE event IN ('$pageview', fc))",
                [UNION],
                [],
            ),
            (
                "subquery_with_name_shadowing_an_outer_with_name",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM "
                "(WITH '$autocapture' AS fc SELECT event FROM events WHERE event IN ('$pageview', fc))",
                ["events"],
                [],
            ),
            (
                "with_constant_in_a_later_branch_of_a_select_set",
                "WITH '$feature_flag_called' AS fc SELECT 1 FROM events WHERE event = '$pageview' "
                "UNION ALL SELECT 1 FROM events WHERE event IN ('$pageview', fc) "
                "UNION ALL (WITH '$autocapture' AS fc SELECT 1 FROM events WHERE event IN ('$pageview', fc))",
                ["events", UNION, "events"],
                [],
            ),
            # The body of `x` reads the outer `fc`, because the inner `fc` comes after `x` in its WITH.
            (
                "with_name_declared_after_the_cte_that_reads_it",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM "
                "(WITH x AS (SELECT count() FROM events WHERE event IN ('$pageview', fc)), '$autocapture' AS fc "
                "SELECT * FROM x)",
                ["x", UNION],
                [],
            ),
            (
                "with_constant_in_a_scan_after_another_table",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM persons AS p JOIN events AS e "
                "ON p.id = e.person_id WHERE e.event IN ('$pageview', fc)",
                ["persons", "events"],
                ["it joins events after another table"],
            ),
            param(
                "with_constant_on_mode_1",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events WHERE event IN ('$pageview', fc)",
                [UNION],
                [],
                only_in_flag_evaluations=False,
            ),
            ("long_with", _long_with(), [UNION], []),
            ("with_list_read_by_many_subqueries", _with_list_read_by_many_subqueries(), [UNION] * 300, []),
            (
                "cte_named_events_after_another_table",
                "WITH events AS (SELECT 1 AS person_id, '$pageview' AS event) "
                f"SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id WHERE {E_MIXED}",
                ["persons", "events"],
                [],
            ),
            (
                "right_join_after_the_scan",
                f"SELECT count() FROM events AS e RIGHT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                ["events", "persons"],
                ["it joins another table to events with RIGHT JOIN"],
            ),
            (
                "final",
                f"SELECT count() FROM events FINAL WHERE {MIXED}",
                ["events"],
                ["it uses FINAL or table arguments on events"],
            ),
            (
                "column_aliases",
                f"SELECT count() FROM events AS e (uuid, event, properties, timestamp, distinct_id, x) WHERE {E_MIXED}",
                ["events"],
                ["it names the events columns with column aliases"],
            ),
            ("sample_ratio", f"SELECT count() FROM events SAMPLE 0.1 WHERE {MIXED}", [UNION], []),
            ("sample_fraction", f"SELECT count() FROM events SAMPLE 1/10 WHERE {MIXED}", [UNION], []),
            (
                "sample_row_count",
                f"SELECT count() FROM events SAMPLE 10 WHERE {MIXED}",
                ["events"],
                ["it uses SAMPLE"],
            ),
            *(
                (
                    f"sample_{name}",
                    f"SELECT count() FROM events SAMPLE {value} WHERE {MIXED}",
                    ["events"],
                    ["it uses SAMPLE"],
                )
                for name, value in (
                    ("inf", "inf"),
                    ("nan", "nan"),
                    ("oversized_integer", "9" * 400),
                    ("oversized_hex_integer", "0x" + "f" * 5000),
                )
            ),
            (
                "sample_with_offset",
                f"SELECT count() FROM events SAMPLE 0.1 OFFSET 0.5 WHERE {MIXED}",
                ["events"],
                ["it uses SAMPLE"],
            ),
            ("select_star", f"SELECT * FROM events WHERE {MIXED}", ["events"], ["it selects * or COLUMNS(...)"]),
            (
                "cte_named_events",
                f"WITH events AS (SELECT '$pageview' AS event) SELECT count() FROM events WHERE {MIXED}",
                ["events"],
                [],
            ),
        ]
    )
    def test_renames_the_scans_the_union_reads_and_names_why_it_cannot_read_the_rest(
        self,
        _name: str,
        query: str | ast.SelectQuery,
        expected_tables: list[str],
        expected_refusals: list[str],
        only_in_flag_evaluations: bool = True,
    ):
        select = _select(query)
        rename = rename_flag_call_scans_to_union(
            select, flag_key_compares_as_string=lambda: True, only_in_flag_evaluations=only_in_flag_evaluations
        )
        collector = _TableCollector()
        collector.visit(select)

        assert collector.tables == expected_tables
        assert [refusal.reason for refusal in rename.refusals] == expected_refusals

    @parameterized.expand(
        [
            (
                "no_flag_call_constant",
                "SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id "
                "WHERE e.event IN ('$pageview', '$autocapture', '$identify')",
                [],
            ),
            (
                "flag_call_constant_elsewhere",
                "SELECT count(), '$feature_flag_called' AS name FROM persons AS p JOIN events AS e ON p.id = e.person_id "
                "WHERE e.event IN ('$pageview', '$autocapture', '$identify')",
                ["it compares `event` with more values than the flag-call check reads"],
            ),
            (
                "flag_call_constant_in_an_outer_with",
                "WITH '$feature_flag_called' AS fc SELECT * FROM (SELECT count() FROM persons AS p "
                "JOIN events AS e ON p.id = e.person_id WHERE e.event IN ('$pageview', '$autocapture', fc))",
                ["it compares `event` with more values than the flag-call check reads"],
            ),
            (
                "flag_call_constant_in_the_first_branch_with",
                "WITH '$feature_flag_called' AS fc SELECT 1 FROM events WHERE event = '$pageview' "
                "UNION ALL SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id "
                "WHERE e.event IN ('$pageview', '$autocapture', fc)",
                ["it compares `event` with more values than the flag-call check reads"],
            ),
        ]
    )
    def test_scan_past_the_compared_values_budget(self, _name: str, query: str, expected_refusals: list[str]):
        select = _select(query)
        with patch("posthog.hogql.transforms.flag_calls_union._COMPARED_VALUES_BUDGET", 2):
            rename = rename_flag_call_scans_to_union(
                select, flag_key_compares_as_string=lambda: True, only_in_flag_evaluations=True
            )

        assert [refusal.reason for refusal in rename.refusals] == expected_refusals

    def test_row_dependent_functions_cover_every_hogql_function_in_their_families(self):
        families = re.compile(
            r"^(rand|random|rowNumber|blockNumber|nowInBlock|generateUUID|generateULID|runningDifference|neighbor)"
        )

        assert [
            name
            for name in HOGQL_CLICKHOUSE_FUNCTIONS
            if families.match(name) and not is_nondeterministic_function(name)
        ] == []


class TestReadFlagCallsWithUnion(BaseTest):
    def _sql(
        self,
        query: str | ast.SelectQuery,
        *,
        mode: FlagEvaluationsMode = READ,
        union: bool = True,
        persons_on_events: PersonsOnEventsMode | None = None,
        new_events_schema: bool | None = None,
        person_id_pushdown: bool | None = None,
        modifiers: HogQLQueryModifiers | None = None,
        inline_cohorts: bool = False,
        in_cohort_via: InCohortVia | None = None,
        rewrite_flag_calls: bool = True,
    ) -> str:
        _set_mode(self.organization, mode)
        with _enabled_flags(union=union), _flag_evaluations_table_in_catalog():
            sql, context = HogQLQueryExecutor(
                query=query,
                team=self.team,
                context=HogQLContext(team_id=self.team.pk, rewrite_flag_calls_to_flag_evaluations=rewrite_flag_calls),
                modifiers=(modifiers or HogQLQueryModifiers()).model_copy(
                    update={
                        "personIdPushdown": person_id_pushdown,
                        "personsOnEventsMode": persons_on_events,
                        "useNewEventsSchema": _events_schema_for(mode, new_events_schema),
                        **({"inlineCohortCalculation": InlineCohortCalculation.ALWAYS} if inline_cohorts else {}),
                        **({"inCohortVia": in_cohort_via} if in_cohort_via else {}),
                    },
                ),
                pretty=False,
            ).generate_clickhouse_sql()
        return substitute_params(sql, context.values)

    @staticmethod
    def _branches(sql: str) -> list[str]:
        start = sql.index("UNION ALL")
        union_start = sql.rindex("(SELECT", 0, sql.rindex("FROM events", 0, start))
        union_end = sql.index(") AS ", sql.rindex("FROM flag_evaluations"))
        return sql[union_start:union_end].split("UNION ALL")

    @parameterized.expand(
        [
            ("mixed_query", f"SELECT count() FROM events WHERE {MIXED}", True, True),
            ("mixed_query_with_the_flag_off", f"SELECT count() FROM events WHERE {MIXED}", False, False),
            (
                "query_phase_1_swaps",
                "SELECT count() FROM events WHERE event = '$feature_flag_called' "
                "AND properties.$feature_flag = 'f' AND timestamp >= now() - INTERVAL 7 DAY",
                True,
                False,
            ),
            # The CTE shadows events, so the query reads the CTE on every mode.
            (
                "cte_named_events",
                f"WITH events AS (SELECT '$pageview' AS event) SELECT count() FROM events WHERE {MIXED}",
                True,
                False,
            ),
            # Each branch reads the raw string of a property without a type, as events does.
            (
                "string_parser_on_an_untyped_property",
                f"SELECT toFloatOrZero(properties.probe) FROM events WHERE {MIXED}",
                True,
                True,
            ),
            param(
                "cte_named_events_on_mode_2",
                f"WITH events AS (SELECT '$pageview' AS event) SELECT count() FROM events WHERE {MIXED}",
                True,
                False,
                mode=ONLY,
            ),
            # Each scan exports its own property columns, so paths that join to one name in separate scans never share a column.
            param(
                "property_paths_of_one_name_in_separate_scans",
                f"SELECT properties.a.b FROM events WHERE {MIXED} UNION ALL "
                f"SELECT properties.a___b FROM events WHERE {MIXED}",
                True,
                True,
                mode=ONLY,
            ),
            param(
                "alias_of_event_in_a_mixed_filter_on_mode_2",
                "SELECT event AS name, count() FROM events "
                "WHERE name IN ('$pageview', '$feature_flag_called') GROUP BY name",
                True,
                True,
                mode=ONLY,
            ),
            param(
                "alias_of_a_comparison_with_flag_calls_on_mode_2",
                "SELECT event = '$feature_flag_called' AS is_flag_call, count() FROM events "
                "WHERE is_flag_call GROUP BY is_flag_call",
                True,
                True,
                mode=ONLY,
            ),
            param(
                "alias_of_the_flag_call_event_name_on_mode_2",
                "SELECT '$feature_flag_called' AS name, count() FROM events WHERE event = name",
                True,
                True,
                mode=ONLY,
            ),
            param(
                "with_constant_in_a_mixed_filter_on_mode_2",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events WHERE event IN ('$pageview', fc)",
                True,
                True,
                mode=ONLY,
            ),
            param(
                "with_constant_pinned_to_only_flag_calls_on_mode_2",
                "WITH '$feature_flag_called' AS fc SELECT count() FROM events WHERE event = fc",
                True,
                True,
                mode=ONLY,
            ),
            # Mode 1 keeps a materialized property on events, so mode 2 shows which columns the union can read.
            param(
                "property_in_a_string_materialized_column_on_mode_2",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                True,
                True,
                mode=ONLY,
                column_type="Nullable(String)",
            ),
            # Each branch reads the property from JSON, so the typed column never reaches the UNION ALL.
            param(
                "typed_materialized_column_on_the_native_events_schema_on_mode_2",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                True,
                True,
                mode=ONLY,
                column_type="Nullable(Float64)",
                new_events_schema=True,
            ),
            # Each branch serializes the key in the SELECT and in the copied filter with functions HogQL can print.
            param(
                "serialized_property_on_the_native_events_schema_on_mode_2",
                f"SELECT toJSONString(properties.probe) FROM events WHERE {MIXED} "
                "AND toJSONString(properties.probe) = '123'",
                True,
                True,
                mode=ONLY,
                new_events_schema=True,
            ),
            param(
                "typed_materialized_column_with_materialization_disabled",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                True,
                True,
                column_type="Nullable(Float64)",
                modifiers=HogQLQueryModifiers(materializationMode=MaterializationMode.DISABLED),
            ),
        ]
    )
    def test_union_reads_the_scans_phase_1_leaves_on_events(
        self,
        _name: str,
        query: str,
        union: bool,
        expected_union: bool,
        mode: FlagEvaluationsMode = READ,
        column_type: str | None = None,
        new_events_schema: bool | None = None,
        modifiers: HogQLQueryModifiers | None = None,
        persons_on_events: PersonsOnEventsMode | None = None,
    ):
        if column_type is not None:
            self.addCleanup(cleanup_materialized_columns)
            materialize("events", "probe", is_nullable=True, column_type=column_type)
        sql = self._sql(
            query,
            union=union,
            mode=mode,
            persons_on_events=persons_on_events,
            new_events_schema=new_events_schema,
            modifiers=modifiers,
        )

        assert ("UNION ALL" in sql) is expected_union
        if expected_union:
            assert re.search(r"FROM flag_evaluations\b", sql) is not None

    @parameterized.expand(
        [
            (
                "right_join",
                f"SELECT count() FROM events AS e RIGHT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED}",
                "RIGHT JOIN",
            ),
            (
                "mixed_scan_after_another_table",
                f"SELECT count() FROM persons AS p JOIN events AS e ON p.id = e.person_id WHERE {E_MIXED}",
                "it joins events after another table",
            ),
            (
                "mixed_scan_after_a_swapped_scan_of_only_flag_calls",
                "SELECT count() FROM persons AS p JOIN events AS a ON p.id = a.person_id "
                "JOIN events AS b ON a.uuid = b.uuid "
                "WHERE a.event = '$feature_flag_called' AND b.event IN ('$pageview', '$feature_flag_called')",
                "it joins events after another table",
            ),
            (
                "field_flag_evaluations_lacks",
                f"SELECT goe_0.properties.plan FROM events WHERE {MIXED}",
                "goe_0.properties",
            ),
            ("sample_row_count", f"SELECT count() FROM events SAMPLE 10 WHERE {MIXED}", "it uses SAMPLE"),
            param(
                "join_whose_on_clause_reads_another_field",
                f"SELECT probe_join.key FROM events WHERE {MIXED}",
                "probe_join",
                warehouse_join=True,
            ),
            (
                "properties_whose_paths_join_to_one_name",
                f"SELECT properties.a.b, properties.a___b FROM events WHERE {MIXED}",
                "properties.a.b and properties.a___b",
            ),
            param(
                "property_in_a_typed_materialized_column",
                f"SELECT properties.probe FROM events WHERE {MIXED}",
                "probe, which events stores in a Nullable\\(Float64\\) column",
                typed_column=True,
            ),
        ]
    )
    def test_mode_1_reads_events_and_mode_2_raises_when_the_union_cannot_read_a_mixed_scan(
        self,
        _name: str,
        query: str,
        reason: str,
        warehouse_join: bool = False,
        typed_column: bool = False,
    ):
        if typed_column:
            self.addCleanup(cleanup_materialized_columns)
            materialize("events", "probe", is_nullable=True, column_type="Nullable(Float64)")
        if warehouse_join:
            # Joined on persons, it reaches events as a join that compares `person.properties.email`, not its key.
            DataWarehouseJoin.objects.create(
                team=self.team,
                source_table_name="persons",
                source_table_key="properties.email",
                joining_table_name="groups",
                joining_table_key="key",
                field_name="probe_join",
            )
        persons_on_events = PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS

        # The native events schema reads every property from JSON, so only the legacy schema reads a typed column.
        new_events_schema = False if typed_column else None
        assert "UNION ALL" not in self._sql(
            query, persons_on_events=persons_on_events, new_events_schema=new_events_schema
        )
        with pytest.raises(QueryError, match=reason):
            self._sql(query, mode=ONLY, persons_on_events=persons_on_events, new_events_schema=new_events_schema)

    @parameterized.expand(
        [
            (
                "scan_after_another_table",
                "SELECT count() FROM (SELECT 'x' AS id) AS d JOIN events AS e ON e.distinct_id = d.id "
                "WHERE e.event = '$feature_flag_called'",
            ),
            (
                "self_join_with_both_sides_pinned",
                "SELECT count() FROM events AS a JOIN events AS b ON a.uuid = b.uuid "
                "WHERE a.event = '$feature_flag_called' AND b.event = '$feature_flag_called'",
            ),
            (
                "filter_on_an_alias_of_event",
                "SELECT event AS name, count() FROM events WHERE name = '$feature_flag_called' GROUP BY name",
            ),
        ]
    )
    def test_mode_2_swaps_scans_of_only_flag_calls_as_it_does_without_the_union(self, _name: str, query: str):
        sql = self._sql(query, mode=ONLY)

        assert sql == self._sql(query, mode=ONLY, union=False)
        assert "UNION ALL" not in sql
        assert "flag_evaluations AS " in sql

    def test_mode_2_self_join_reads_its_mixed_side_from_the_union_and_its_flag_call_side_from_flag_evaluations(
        self,
    ):
        sql = self._sql(
            "SELECT count() FROM events AS a JOIN events AS b ON a.uuid = b.uuid "
            "WHERE a.event IN ('$pageview', '$feature_flag_called') AND b.event = '$feature_flag_called'",
            mode=ONLY,
        )

        assert "UNION ALL" in sql
        assert "JOIN flag_evaluations AS b" in sql

    @parameterized.expand(
        [
            ("mode_0_native", FLAG_CALLS, EVENTS, True, True),
            ("mode_0_native_keyed_and_bounded", KEYED_BOUNDED_FLAG_CALLS, EVENTS, True, True),
            ("mode_1_native", FLAG_CALLS, READ, True, True),
            ("mode_1_native_keyed_and_bounded", KEYED_BOUNDED_FLAG_CALLS, READ, True, True),
            ("mode_2_native", FLAG_CALLS, ONLY, True, True),
            ("mode_0_legacy_keyed_and_bounded", KEYED_BOUNDED_FLAG_CALLS, EVENTS, False, False),
            # Mode 1 on the legacy table still needs a flag key and a time bound to swap.
            ("mode_1_legacy", FLAG_CALLS, READ, False, False),
            ("mode_1_legacy_keyed_and_bounded", KEYED_BOUNDED_FLAG_CALLS, READ, False, True),
            ("mode_2_legacy", FLAG_CALLS, ONLY, False, True),
        ]
    )
    def test_flag_call_scan_reads_flag_evaluations_on_the_native_events_schema_whatever_the_mode(
        self, _name: str, query: str, mode: FlagEvaluationsMode, new_events_schema: bool, reads_flag_evaluations: bool
    ):
        _set_mode(self.organization, mode)
        with _flag_evaluations_table_in_catalog():
            assert Database.create_for(team=self.team).has_table(["posthog", "flag_evaluations"])

        sql = self._sql(query, mode=mode, union=False, new_events_schema=new_events_schema)

        assert (re.search(r"FROM flag_evaluations\b", sql) is not None) is reads_flag_evaluations

    @parameterized.expand([("mode_0", EVENTS), ("mode_1", READ)])
    def test_flag_call_scan_on_the_native_events_schema_prints_what_mode_2_prints(
        self, _name: str, mode: FlagEvaluationsMode
    ):
        sql = self._sql(FLAG_CALLS, mode=mode, union=False, new_events_schema=True)

        assert sql == self._sql(FLAG_CALLS, mode=ONLY, union=False, new_events_schema=True)

    @parameterized.expand(
        [
            ("mode_0_native_select_star", f"SELECT * {FLAG_CALLS_FROM}", EVENTS, True, "it selects \\* or COLUMNS"),
            ("mode_1_native_select_star", f"SELECT * {FLAG_CALLS_FROM}", READ, True, "it selects \\* or COLUMNS"),
            ("mode_2_native_select_star", f"SELECT * {FLAG_CALLS_FROM}", ONLY, True, "it selects \\* or COLUMNS"),
            ("mode_0_native_sample", SAMPLED_FLAG_CALLS, EVENTS, True, "it uses SAMPLE"),
            ("mode_2_native_sample", SAMPLED_FLAG_CALLS, ONLY, True, "it uses SAMPLE"),
            ("mode_0_legacy_select_star", f"SELECT * {FLAG_CALLS_FROM}", EVENTS, False, None),
            ("mode_1_legacy_select_star", f"SELECT * {FLAG_CALLS_FROM}", READ, False, None),
        ]
    )
    def test_flag_call_shape_flag_evaluations_cannot_answer_raises_on_the_native_events_schema(
        self, _name: str, query: str, mode: FlagEvaluationsMode, new_events_schema: bool, reason: str | None
    ):
        if reason is None:
            assert "flag_evaluations" not in self._sql(
                query, mode=mode, union=False, new_events_schema=new_events_schema
            )
            return
        with pytest.raises(QueryError, match=reason):
            self._sql(query, mode=mode, union=False, new_events_schema=new_events_schema)

    @parameterized.expand(
        [
            ("mode_0_native", EVENTS, True),
            ("mode_1_native", READ, True),
            ("mode_2_native", ONLY, True),
            ("mode_2_legacy", ONLY, False),
        ]
    )
    def test_context_without_the_flag_call_rewrite_reads_flag_calls_from_events(
        self, _name: str, mode: FlagEvaluationsMode, new_events_schema: bool
    ):
        sql = self._sql(
            FLAG_CALLS, mode=mode, union=False, new_events_schema=new_events_schema, rewrite_flag_calls=False
        )

        assert "flag_evaluations" not in sql

    @parameterized.expand([("dotted", UNION), ("quoted", f"`{UNION}`")])
    def test_query_cannot_name_the_union_table(self, _name: str, table: str):
        with pytest.raises(QueryError, match="Unknown table `posthog.events_with_flag_calls`"):
            self._sql(f"SELECT count() FROM {table}")

    def test_in_subquery_over_the_union_runs_once_with_global_in(self):
        sql = self._sql(
            f"SELECT count() FROM events WHERE distinct_id IN (SELECT distinct_id FROM events WHERE {MIXED})"
        )

        assert "globalIn(events.distinct_id" in sql

    @parameterized.expand(
        [
            ("restricted_on_mode_1", READ, None, False, False),
            # Mode 2 reads every flag call from flag_evaluations, so it never asks events for the flag key.
            ("restricted_on_mode_2", ONLY, None, False, True),
            ("boolean_on_native_json_on_mode_1", READ, "Boolean", True, True),
            ("numeric_on_native_json_on_mode_1", READ, "Numeric", True, True),
            ("boolean_on_native_json_on_mode_0", EVENTS, "Boolean", True, True),
            ("boolean_on_native_json_on_mode_2", ONLY, "Boolean", True, True),
        ]
    )
    def test_flag_key_that_events_cannot_read_raw_keeps_legacy_mode_1_on_events(
        self, _name: str, mode: FlagEvaluationsMode, flag_key_type: str | None, new_events_schema: bool, expected: bool
    ):
        if flag_key_type is None:
            _restrict(self.organization, self.team, "$feature_flag")
        else:
            PropertyDefinition.objects.create(
                team=self.team, name="$feature_flag", property_type=flag_key_type, type=PropertyDefinition.Type.EVENT
            )

        sql = self._sql(f"SELECT count() FROM events WHERE {MIXED}", mode=mode, new_events_schema=new_events_schema)

        assert ("UNION ALL" in sql) is expected

    @parameterized.expand(
        [
            (
                "one_key",
                "if(event = '$feature_flag_called' AND properties.$feature_flag = 'probe-flag', 1, 0) AS step_1",
                "step_1 = 1",
                "tuple('probe-flag')",
            ),
            (
                "a_key_per_step_with_other_conditions",
                "if(event = '$feature_flag_called' AND properties.$feature_flag = 'a' AND properties.x = '1', 1, 0) "
                "AS step_1, "
                "if(event = '$feature_flag_called' AND properties.$feature_flag = 'b' AND properties.x = '2', 1, 0) "
                "AS step_2",
                "step_1 = 1 OR step_2 = 1",
                "tuple('a', 'b')",
            ),
        ]
    )
    def test_funnel_steps_on_flag_keys_read_only_those_keys_and_skip_keyless_calls(
        self, _name: str, flag_steps: str, flag_step_filter: str, keys: str
    ):
        # The shape a funnel runner builds: one column per step, and a filter that keeps a row matching any step.
        sql = self._sql(
            "SELECT * FROM ("
            f"SELECT if(event = '$pageview', 1, 0) AS step_0, {flag_steps} "
            "FROM events WHERE timestamp >= toDateTime('2026-10-01') AND timestamp <= toDateTime('2026-10-20') "
            f"AND event IN ('$feature_flag_called', '$pageview') AND (step_0 = 1 OR {flag_step_filter}))"
        )

        events, flag_evaluations = self._branches(sql)
        for branch in (events, flag_evaluations):
            assert "2026-10-01" in branch and "2026-10-20" in branch
        assert f"in(flag_evaluations.flag_key, {keys})" in flag_evaluations
        assert "in(events.event, tuple('$feature_flag_called', '$pageview'))" in events

    @parameterized.expand(
        [
            ("no_flag_key_filter", "", None),
            # A Boolean type converts the key before the comparison, so 'TRUE' also matches the JSON value true.
            ("boolean_flag_key", " AND properties.$feature_flag = 'TRUE'", "Boolean"),
        ]
    )
    def test_query_without_a_string_flag_key_reads_keyless_calls_from_events(
        self, _name: str, flag_key_filter: str, flag_key_type: str | None
    ):
        if flag_key_type is not None:
            PropertyDefinition.objects.create(
                team=self.team, name="$feature_flag", property_type=flag_key_type, type=PropertyDefinition.Type.EVENT
            )

        events, keyless, flag_evaluations = self._branches(
            self._sql(f"SELECT count() FROM events WHERE {MIXED} AND distinct_id = 'probe'{flag_key_filter}")
        )

        for branch in (events, keyless):
            assert "equals(events.distinct_id, 'probe')" in branch
        assert "equals(flag_evaluations.distinct_id, 'probe')" in flag_evaluations
        assert "flag_key" not in flag_evaluations

    @parameterized.expand(
        [
            ("array_join", "arrayJoin(['a', 'b']) = 'a'", "arrayJoin"),
            ("random", "rand() % 10 = 0", "rand"),
            ("row_number", "rowNumberInBlock() < 5", "rowNumberInBlock"),
            ("random_in_upper_case", "RAND() % 10 = 0", "rand"),
            ("now_in_block", "timestamp < nowInBlock('UTC')", "nowInBlock"),
        ]
    )
    def test_filter_that_depends_on_each_read_stays_out_of_the_branches(self, _name: str, condition: str, name: str):
        sql = self._sql(f"SELECT count() FROM events WHERE {MIXED} AND {condition}")

        assert all(name not in branch for branch in self._branches(sql))
        assert name in sql

    def test_sample_one_adds_no_warning(self):
        _set_mode(self.organization, READ)
        with _enabled_flags(union=True):
            _, context = HogQLQueryExecutor(
                query=f"SELECT count() FROM events SAMPLE 1 WHERE {MIXED}", team=self.team
            ).generate_clickhouse_sql()

        assert context.warnings == []

    def test_ratio_sample_applies_in_every_branch_and_warns_of_nothing(self):
        _set_mode(self.organization, READ)
        query = f"SELECT count() FROM events SAMPLE 0.1 WHERE {MIXED}"
        with _enabled_flags(union=True):
            sql, context = HogQLQueryExecutor(
                query=query, team=self.team, modifiers=HogQLQueryModifiers(useNewEventsSchema=False), pretty=False
            ).generate_clickhouse_sql()
        branches = self._branches(substitute_params(sql, context.values))

        assert context.warnings == []
        assert [("SAMPLE 0.1" in branch) for branch in branches] == [True, True, False]
        assert "less(cityHash64(flag_evaluations.distinct_id), 1844674407370955161)" in branches[-1]

    def test_ratio_sample_applies_when_a_joined_person_field_reads_a_second_union_scan(self):
        sql = self._sql(
            f"SELECT person.properties.email, count() FROM events SAMPLE 0.1 WHERE {MIXED} GROUP BY 1",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            person_id_pushdown=False,
        )

        assert sql.count("SAMPLE 0.1") == 2
        assert "less(cityHash64(flag_evaluations.distinct_id), 1844674407370955161)" in sql

    @parameterized.expand(
        [
            ("subquery_on_mode_1", READ, InCohortVia.SUBQUERY, False),
            ("subquery_on_mode_2", ONLY, InCohortVia.SUBQUERY, True),
            ("leftjoin_on_mode_2", ONLY, InCohortVia.LEFTJOIN, True),
            # IN COHORT splices the cohort in before the swap, which then reads its scans on either mode.
            ("conjoined_on_mode_1", READ, InCohortVia.LEFTJOIN_CONJOINED, True),
            ("conjoined_on_mode_2", ONLY, InCohortVia.LEFTJOIN_CONJOINED, True),
        ]
    )
    def test_inline_cohort_reads_flag_calls_from_flag_evaluations_only_on_mode_2(
        self, _name: str, mode: FlagEvaluationsMode, via: InCohortVia, expected_flag_evaluations: bool
    ):
        cohort = _performed_flag_call_cohort(self.team, "probe-flag")

        sql = self._sql(
            f"SELECT count() FROM events WHERE person_id IN COHORT {cohort.pk}",
            mode=mode,
            inline_cohorts=True,
            in_cohort_via=via,
        )

        assert (re.search(r"FROM flag_evaluations\b", sql) is not None) is expected_flag_evaluations

    @parameterized.expand(
        [
            ("outer_query_names_no_flag_calls", "SELECT count() FROM events WHERE person_id IN COHORT {cohort}"),
            (
                "outer_query_excludes_flag_calls",
                "SELECT count() FROM events WHERE event != '$feature_flag_called' AND person_id IN COHORT {cohort}",
            ),
            (
                "outer_query_swapped_by_phase_1",
                "SELECT count() FROM events WHERE event = '$feature_flag_called' AND person_id IN COHORT {cohort}",
            ),
            (
                "left_join_cohort",
                "SELECT count() FROM events WHERE person_id IN COHORT {cohort}",
                InCohortVia.LEFTJOIN,
            ),
        ]
    )
    def test_mode_2_raises_when_an_inline_cohort_reads_a_field_the_union_cannot_supply(
        self, _name: str, outer_query: str, via: InCohortVia | None = None
    ):
        self.addCleanup(cleanup_materialized_columns)
        materialize("events", "probe", is_nullable=True, column_type="Nullable(Float64)")
        cohort = _performed_flag_call_cohort(self.team, "probe-flag")
        cohort_query = parse_select(
            "SELECT person_id AS id FROM events WHERE event = '$feature_flag_called' "
            "AND properties.probe > 1 GROUP BY person_id"
        )

        with (
            patch("posthog.hogql_queries.hogql_cohort_query.HogQLCohortQuery.get_query", return_value=cohort_query),
            pytest.raises(QueryError, match="probe, which events stores in a Nullable"),
        ):
            self._sql(
                outer_query.format(cohort=cohort.pk),
                mode=ONLY,
                inline_cohorts=True,
                in_cohort_via=via,
                new_events_schema=False,
            )

    @parameterized.expand(
        [
            ("flag_calls_only", "SELECT count() FROM events SAMPLE 0.1 WHERE event = '$feature_flag_called'"),
            (
                "flag_calls_only_next_to_a_join",
                "SELECT count() FROM events AS e SAMPLE 0.1 LEFT JOIN persons AS p ON e.person_id = p.id "
                "WHERE e.event = '$feature_flag_called'",
            ),
        ]
    )
    def test_mode_2_reads_a_sampled_flag_call_scan_from_the_union(self, _name: str, query: str):
        sql = self._sql(query, mode=ONLY)

        assert re.search(r"FROM flag_evaluations\b", sql) is not None
        assert "less(cityHash64(flag_evaluations.distinct_id), 1844674407370955161)" in sql

    def test_sessions_join_keeps_its_time_bound(self):
        sql = self._sql(
            f"SELECT session.$session_duration FROM events WHERE {MIXED} "
            "AND timestamp >= toDateTime('2026-10-01') AND timestamp < toDateTime('2026-10-08')"
        )

        sessions = sql[sql.index("FROM raw_sessions") : sql.index("AS events__session")]
        assert "toDateTime('2026-10-01', 'UTC')" in sessions and "toDateTime('2026-10-08', 'UTC')" in sessions

    def test_sessions_join_keeps_a_literal_session_id_filter(self):
        sql = self._sql(
            f"SELECT session.$session_duration FROM events WHERE {MIXED} AND $session_id IN ('{SESSION_ID}')"
        )

        sessions = sql[sql.index("FROM raw_sessions") : sql.index("AS events__session")]
        assert (
            f"in(raw_sessions.session_id_v7, tuple(toUInt128(accurateCastOrNull('{SESSION_ID}', 'UUID'))))" in sessions
        )

    def test_persons_join_keeps_the_person_id_pushdown(self):
        sql = self._sql(
            f"SELECT person.properties.email FROM events WHERE {MIXED} AND distinct_id = 'probe-distinct-id'",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            person_id_pushdown=True,
        )

        persons = sql[sql.index("FROM person_distinct_id_overrides") :]
        assert "GLOBAL IN" in sql or "globalIn" in sql
        assert "probe-distinct-id" in persons

    @parameterized.expand(
        [
            ("union", f"FROM events WHERE {MIXED}", None, True),
            (
                "flag_calls_swapped_to_flag_evaluations",
                "FROM events WHERE event = '$feature_flag_called' AND properties.$feature_flag = 'f'",
                None,
                True,
            ),
            ("flag_evaluations", "FROM posthog.flag_evaluations WHERE flag_key = 'f'", None, True),
            ("flag_evaluations_turned_off", "FROM posthog.flag_evaluations WHERE flag_key = 'f'", False, False),
            ("events_only", "FROM events WHERE event = '$pageview'", None, False),
        ]
    )
    def test_person_id_pushdown_defaults_on_for_flag_evaluations(
        self, _name: str, from_where: str, person_id_pushdown: bool | None, pushed: bool
    ):
        sql = self._sql(
            f"SELECT person.properties.email {from_where} AND timestamp >= now() - INTERVAL 7 DAY",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            person_id_pushdown=person_id_pushdown,
        )

        persons = sql[sql.index("FROM person_distinct_id_overrides") :]
        assert ("SELECT DISTINCT" in persons) is pushed

    @parameterized.expand(
        [
            (
                "session_id_pushdown_selects_the_scans_sessions",
                f"SELECT session.$session_duration FROM events WHERE {MIXED}",
                PersonsOnEventsMode.DISABLED,
                {"sessionIdPushdown": True},
                "globalIn(raw_sessions.session_id_v7, (SELECT DISTINCT",
                None,
                None,
            ),
            (
                "negated_person_filter_becomes_an_exclusion",
                f"SELECT count() FROM events WHERE {MIXED} AND person.properties.mykey != 'x'",
                PersonsOnEventsMode.DISABLED,
                {"negatedPersonFiltersNotIn": True},
                "notIn(events__pdi.person_id, (SELECT persons.id",
                "ifNull(notEquals(events__pdi__person.",
                None,
            ),
            (
                "limit_caps_the_scan_before_the_left_join",
                f"SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} "
                "LIMIT 10",
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                {},
                "LIMIT 10) AS e LEFT JOIN",
                "WHERE in(e.event",
                "WHERE in(event, tuple('$pageview', '$feature_flag_called')) LIMIT 10) AS e LEFT JOIN",
            ),
        ]
    )
    def test_union_scan_keeps_the_pushdown_that_events_gets(
        self,
        _name: str,
        query: str,
        persons_on_events: PersonsOnEventsMode,
        modifiers: dict[str, Any],
        pushed: str,
        not_pushed: str | None,
        union_pushed: str | None,
    ):
        self.addCleanup(cleanup_materialized_columns)
        materialize("events", "mykey")
        materialize("person", "mykey")

        for union in (False, True):
            sql = self._sql(
                query, union=union, persons_on_events=persons_on_events, modifiers=HogQLQueryModifiers(**modifiers)
            )

            assert (UNION_EXPANSION in sql) == union
            assert pushed in sql
            assert not_pushed is None or not_pushed not in sql
            assert not union or union_pushed is None or union_pushed in sql
            if union and "globalIn(raw_sessions.session_id_v7" in pushed:
                sessions_subquery = sql[
                    sql.index("globalIn(raw_sessions.session_id_v7") : sql.index("AS events__session")
                ]
                assert UNION_EXPANSION in sessions_subquery

    @parameterized.expand(
        [
            (
                "order_by",
                f"SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} ORDER BY e.timestamp LIMIT 10",
            ),
            (
                "inner_join",
                f"SELECT e.event, p.id FROM events AS e INNER JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} LIMIT 10",
            ),
            (
                "filter_on_a_joined_table",
                f"SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} AND p.id != e.person_id LIMIT 10",
            ),
            (
                "filter_on_a_property",
                f"SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} AND e.properties.mykey = 'a' LIMIT 10",
            ),
            (
                "row_multiplying_filter",
                f"SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} AND arrayJoin(['a', 'b']) = 'a' LIMIT 10",
            ),
            (
                "nondeterministic_filter",
                f"SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} AND rand() % 2 = 0 LIMIT 10",
            ),
            (
                "subquery_filter",
                f"SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} AND e.person_id IN (SELECT id FROM persons) LIMIT 10",
            ),
            (
                "row_multiplying_select",
                f"SELECT e.event, arrayJoin(JSONExtractArrayRaw(e.properties, 'items')) AS item, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id WHERE {E_MIXED} LIMIT 10",
            ),
        ]
    )
    def test_union_scan_keeps_its_filter_after_the_limit_when_the_limit_would_change_rows(self, _name: str, query: str):
        sql = self._sql(query, persons_on_events=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS)

        assert UNION_EXPANSION in sql
        assert "LIMIT 10) AS e" not in sql

    def test_union_scan_keeps_a_cohort_filter_outside_the_scan(self):
        cohort = Cohort.objects.create(team=self.team, name="static", is_static=True)
        query = (
            "SELECT e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id "
            f"WHERE {E_MIXED} AND e.person_id IN COHORT {cohort.pk} LIMIT 10"
        )

        sql = self._sql(
            query,
            persons_on_events=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
            modifiers=HogQLQueryModifiers(inCohortVia="leftjoin"),
        )

        assert UNION_EXPANSION in sql
        assert "LIMIT 10) AS e" not in sql

    def test_union_scan_pushdown_ignores_a_user_written_aggregating_subquery(self):
        sql = self._sql(
            "SELECT s.n FROM (SELECT count() AS n FROM (SELECT event FROM events UNION ALL SELECT event FROM events)) "
            "AS s LEFT JOIN persons AS p ON p.id = s.n WHERE s.n > 0 LIMIT 10",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
        )

        assert "WHERE greater(s.n, 0) LIMIT 10" in sql

    def test_persons_join_runs_one_override_join(self):
        sql = self._sql(
            f"SELECT person_id, person.properties.email FROM events WHERE {MIXED}",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            person_id_pushdown=False,
        )

        assert sql.count("FROM person_distinct_id_overrides") == 2  # one inner, one outer for `person_id`

    def test_typed_property_converts_once_at_its_read_and_stays_raw_in_the_branches(self):
        for kind in (PropertyDefinition.Type.EVENT, PropertyDefinition.Type.PERSON):
            PropertyDefinition.objects.create(team=self.team, name="amount", property_type="Numeric", type=kind)
        sql = self._sql(
            f"SELECT toFloatOrZero(properties.amount), properties.amount FROM events "
            f"WHERE {MIXED} AND properties.amount > 9 AND person.properties.amount > 9",
            persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            person_id_pushdown=False,
        )

        assert "accurateCastOrNull(accurateCastOrNull" not in sql
        assert "toFloat64OrZero(events.properties___amount)" in sql
        for branch in self._branches(sql):
            projection, _, where = branch.partition(" FROM ")
            assert "accurateCastOrNull" not in projection
            assert where.count("accurateCastOrNull") == 1
        # The persons join comes after the union, so it converts its property as it does on events.
        assert "accurateCastOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, 'amount')" in sql


class TestFlagCallsUnionRows(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        now = datetime.now(UTC)
        self.recent = _create_person(distinct_ids=["recent"], team_id=self.team.pk, properties={"email": "r@x.com"})
        self.old = _create_person(distinct_ids=["old"], team_id=self.team.pk, properties={"email": "o@x.com"})
        for distinct_id, person, days_ago in (("recent", self.recent, 3), ("old", self.old, 100)):
            _create_event(
                event="$pageview",
                distinct_id=distinct_id,
                person_id=person.uuid,
                person_properties={"email": person.properties["email"]},
                team=self.team,
                timestamp=now - timedelta(days=days_ago),
            )
        # Ingestion writes a keyed flag call to both tables on mode 1. Only flag_evaluations has the stale person,
        # which an override corrects.
        flag_call_uuid = uuid.uuid4()
        _create_event(
            event_uuid=flag_call_uuid,
            event="$feature_flag_called",
            distinct_id="recent",
            person_id=self.recent.uuid,
            person_properties={"email": "r@x.com"},
            team=self.team,
            timestamp=now - timedelta(days=2),
            properties={"$feature_flag": "probe-flag", "source": "events"},
        )
        _create_flag_evaluations(
            self.team.pk,
            "probe-flag",
            timestamp=now - timedelta(days=2),
            distinct_id="recent",
            person_id=uuid.uuid4(),
            person_properties={"email": "r@x.com"},
            properties={"source": "flag_evaluations"},
        )
        sync_execute(
            "INSERT INTO person_distinct_id_overrides (team_id, distinct_id, person_id, version) VALUES",
            [(self.team.pk, "recent", str(self.recent.uuid), 1)],
        )
        _create_event(
            event="$feature_flag_called",
            distinct_id="old",
            person_id=self.old.uuid,
            team=self.team,
            timestamp=now - timedelta(days=99),
            properties={"$feature_flag": "probe-flag", "source": "events"},
        )
        for distinct_id, flag_key in (("missing", None), ("empty", ""), ("number", 100)):
            _create_event(
                event="$feature_flag_called",
                distinct_id=distinct_id,
                team=self.team,
                timestamp=now - timedelta(days=1),
                properties={"source": "events", **({} if flag_key is None else {"$feature_flag": flag_key})},
            )
        flush_persons_and_events()

    def _run(
        self,
        query: str | ast.SelectQuery,
        mode: FlagEvaluationsMode,
        persons_on_events: PersonsOnEventsMode | None = None,
        new_events_schema: bool | None = None,
        **modifiers: Any,
    ):
        _set_mode(self.organization, mode)
        with _enabled_flags(union=True):
            return execute_hogql_query(
                query,
                team=self.team,
                modifiers=HogQLQueryModifiers(
                    personsOnEventsMode=persons_on_events,
                    useNewEventsSchema=_events_schema_for(mode, new_events_schema),
                    **modifiers,
                ),
            )

    def _flag_calls_read_at_each_execution(
        self, query: str, mode: FlagEvaluationsMode, **modifiers: Any
    ) -> list[list[str] | None]:
        tagged: list[list[str] | None] = []

        def record_tag(*args: Any, **kwargs: Any):
            tagged.append(json.loads(get_query_tags().to_json()).get("flag_calls_read"))
            return sync_execute(*args, **kwargs)

        with patch("posthog.hogql.query.sync_execute", side_effect=record_tag):
            self._run(query, mode, **modifiers)
        return tagged

    @parameterized.expand(
        [
            *(
                (f"{mode.name.lower()}_{poe.name.lower()}", mode, poe)
                for mode in (FlagEvaluationsMode.READ_FLAG_EVALUATIONS, FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY)
                for poe in (
                    PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                    PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                )
            ),
            param(
                "filter_on_an_alias_of_event",
                ONLY,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                event="event AS name",
                event_filter="name IN ('$pageview', '$feature_flag_called')",
            ),
            param(
                "filter_on_a_with_constant",
                ONLY,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                ctes="WITH '$feature_flag_called' AS fc",
                event_filter="event IN ('$pageview', fc)",
            ),
        ]
    )
    def test_each_flag_call_comes_from_one_table(
        self,
        _name: str,
        mode: FlagEvaluationsMode,
        poe: PersonsOnEventsMode,
        event: str = "event",
        event_filter: str = MIXED,
        ctes: str = "",
    ):
        response = self._run(
            f"""
            {ctes}
            SELECT distinct_id, {event}, properties.source, person_id, person.properties.email
            FROM events
            WHERE {event_filter} AND timestamp >= now() - INTERVAL 120 DAY
            ORDER BY timestamp, distinct_id
            """,
            mode,
            poe,
        )

        recent_id, old_id = str(self.recent.uuid), str(self.old.uuid)
        history = [
            ("old", "$pageview", None, old_id, "o@x.com"),
            ("old", "$feature_flag_called", "events", old_id, "o@x.com"),
        ]
        recent = [
            ("recent", "$pageview", None, recent_id, "r@x.com"),
            ("recent", "$feature_flag_called", "flag_evaluations", recent_id, "r@x.com"),
        ]
        keyless = [(distinct_id, "$feature_flag_called", "events") for distinct_id in ("empty", "missing", "number")]
        rows = [
            tuple(str(value) if isinstance(value, uuid.UUID) else value for value in row) for row in response.results
        ]
        if mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY:
            assert rows == [history[0], *recent]
        else:
            assert rows[:4] == [*history, *recent]
            assert [row[:3] for row in rows[4:]] == keyless

    @parameterized.expand([("read_flag_evaluations", READ), ("flag_evaluations_only", ONLY)])
    def test_flag_only_and_mixed_queries_count_a_call_from_before_the_coverage_start(
        self, _name: str, mode: FlagEvaluationsMode
    ):
        # Mode 2 writes a flag call only to flag_evaluations.
        timestamp = datetime.now(UTC) - timedelta(days=FLAG_EVALUATIONS_COMPLETE_DAYS + 1)
        if mode == READ:
            _create_event(
                event="$feature_flag_called",
                distinct_id="edge",
                team=self.team,
                timestamp=timestamp,
                properties={"$feature_flag": "edge-flag"},
            )
            flush_persons_and_events()
        _create_flag_evaluations(self.team.pk, "edge-flag", timestamp=timestamp, distinct_id="edge")
        bound = f"distinct_id = 'edge' AND timestamp >= now() - INTERVAL {FLAG_EVALUATIONS_COMPLETE_DAYS + 3} DAY"

        flag_only = self._run(f"SELECT count() FROM events WHERE event = '$feature_flag_called' AND {bound}", mode)
        mixed = self._run(f"SELECT countIf(event = '$feature_flag_called') FROM events WHERE {MIXED} AND {bound}", mode)

        assert (flag_only.results, mixed.results) == ([(1,)], [(1,)])

    def test_inline_cohort_counts_flag_calls_that_only_flag_evaluations_holds(self):
        fresh = _create_person(distinct_ids=["fresh"], team_id=self.team.pk)
        _create_flag_evaluations(
            self.team.pk,
            "fresh-flag",
            timestamp=datetime.now(UTC) - timedelta(days=2),
            distinct_id="fresh",
            person_id=fresh.uuid,
        )
        flush_persons_and_events()
        cohort = _performed_flag_call_cohort(self.team, "fresh-flag")
        _set_mode(self.organization, ONLY)
        with _enabled_flags(union=True):
            response = execute_hogql_query(
                f"SELECT id FROM persons WHERE id IN COHORT {cohort.pk}",
                team=self.team,
                modifiers=HogQLQueryModifiers(inlineCohortCalculation=InlineCohortCalculation.ALWAYS),
            )

        assert [str(row[0]) for row in response.results] == [str(fresh.uuid)]

    @parameterized.expand(
        [
            ("union", READ, f"SELECT count() FROM events WHERE {MIXED}", ["union"]),
            ("swap", ONLY, "SELECT count() FROM events WHERE event = '$feature_flag_called'", ["flag_evaluations"]),
            (
                "union_and_swap",
                ONLY,
                "SELECT count() FROM events AS a JOIN events AS b ON a.uuid = b.uuid "
                f"WHERE a.{MIXED} AND b.event = '$feature_flag_called'",
                ["flag_evaluations", "union"],
            ),
            ("inline_cohort", ONLY, "SELECT id FROM persons WHERE id IN COHORT {cohort}", ["union"]),
            ("no_flag_calls", ONLY, "SELECT count() FROM events WHERE event = '$pageview'", None),
            (
                "declined_union",
                READ,
                f"SELECT properties.a.b, properties.a___b FROM events WHERE {MIXED}",
                None,
            ),
            (
                "declined_swap",
                READ,
                "SELECT count() FROM posthog.events "
                "JOIN (SELECT distinct_id AS d, properties AS posthog FROM events) AS s ON distinct_id = s.d "
                "WHERE posthog.events.event = '$feature_flag_called' "
                "AND posthog.events.properties.$feature_flag = 'probe-flag' "
                "AND posthog__events.timestamp >= now() - INTERVAL 7 DAY",
                None,
            ),
        ]
    )
    def test_log_comment_names_the_rewrites_that_read_flag_calls(
        self, _name: str, mode: FlagEvaluationsMode, query: str, expected: list[str] | None
    ):
        cohort = _performed_flag_call_cohort(self.team, "probe-flag")

        tagged = self._flag_calls_read_at_each_execution(
            query.format(cohort=cohort.pk), mode, inlineCohortCalculation=InlineCohortCalculation.ALWAYS
        )

        assert tagged == [expected]

    @override_settings(AI_GATEWAY_URL="https://gateway.example.com/v1", AI_GATEWAY_API_KEY="test-key")
    def test_jev_source_query_keeps_its_tag_out_of_the_query_that_reads_its_rows(self):
        with patch("httpx.AsyncClient.post", side_effect=gateway_response):
            tagged = self._flag_calls_read_at_each_execution(
                "SELECT jev(event, 'Flag call?') AS p FROM events WHERE event = '$feature_flag_called'", ONLY
            )

        assert tagged == [["flag_evaluations"], None]

    def test_ratio_sample_keeps_the_same_distinct_ids_in_both_tables(self):
        now = datetime.now(UTC)
        for index in range(100):
            distinct_id = f"sampled-{index}"
            _create_event(event="$pageview", distinct_id=distinct_id, team=self.team, timestamp=now)
            _create_flag_evaluations(
                self.team.pk, "sample-flag", timestamp=now, distinct_id=distinct_id, person_id=uuid.uuid4()
            )
        flush_persons_and_events()

        response = self._run(
            f"SELECT event, groupUniqArray(distinct_id) FROM events SAMPLE 0.3 "
            f"WHERE {MIXED} AND startsWith(distinct_id, 'sampled-') GROUP BY event",
            ONLY,
        )

        sampled = {event: set(ids) for event, ids in response.results}
        assert 0 < len(sampled["$pageview"]) < 100
        assert sampled["$feature_flag_called"] == sampled["$pageview"]

    @parameterized.expand(
        [
            (
                "person_id_pushdown",
                f"SELECT distinct_id, event, person.properties.email FROM events WHERE {MIXED} ORDER BY timestamp, distinct_id",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                "personIdPushdown",
            ),
            (
                "negated_person_filters",
                f"SELECT distinct_id, event FROM events WHERE {MIXED} AND person.properties.email != 'o@x.com' "
                "ORDER BY timestamp, distinct_id",
                PersonsOnEventsMode.DISABLED,
                "negatedPersonFiltersNotIn",
            ),
            (
                "negated_person_filters_on_the_override_join",
                f"SELECT distinct_id, event FROM events WHERE {MIXED} AND person.properties.email != 'r@x.com' "
                "ORDER BY timestamp, distinct_id",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                "negatedPersonFiltersNotIn",
            ),
            (
                "session_id_pushdown",
                f"SELECT distinct_id, event, session.$session_duration FROM events WHERE {MIXED} "
                "ORDER BY timestamp, distinct_id",
                PersonsOnEventsMode.DISABLED,
                "sessionIdPushdown",
            ),
            (
                "limit_before_the_left_join",
                f"SELECT e.distinct_id, e.event, p.id FROM events AS e LEFT JOIN persons AS p ON e.person_id = p.id "
                f"WHERE {E_MIXED} AND e.timestamp >= now() - INTERVAL 120 DAY LIMIT 100",
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                "pushDownPredicates",
            ),
        ]
    )
    def test_pushdown_does_not_change_the_rows(self, _name: str, query: str, poe: PersonsOnEventsMode, modifier: str):
        self.addCleanup(cleanup_materialized_columns)
        materialize("person", "email")

        pushed = self._run(query, READ, poe, **{modifier: True}).results
        flat = self._run(query, READ, poe, **{modifier: False}).results

        assert len(pushed) >= 2
        assert sorted(map(str, pushed)) == sorted(map(str, flat))

    @parameterized.expand(
        [
            (f"{kind.name.lower()}_{mode.name.lower()}", kind, mode)
            for kind in (PropertyDefinition.Type.EVENT, PropertyDefinition.Type.PERSON)
            for mode in (READ, ONLY)
        ]
    )
    def test_string_parser_reads_the_raw_value_of_a_typed_property(
        self, _name: str, kind: PropertyDefinition.Type, mode: FlagEvaluationsMode
    ):
        PropertyDefinition.objects.create(team=self.team, name="amount", property_type="Numeric", type=kind)
        now = datetime.now(UTC)
        person = _create_person(distinct_ids=["typed"], team_id=self.team.pk)
        for amount in ("9", "20"):
            _create_event(
                event="$pageview",
                distinct_id="typed",
                person_id=person.uuid,
                person_properties={"amount": amount},
                team=self.team,
                timestamp=now - timedelta(days=1),
                properties={"amount": amount},
            )
        _create_event(
            event="$feature_flag_called",
            distinct_id="typed",
            person_id=person.uuid,
            person_properties={"amount": "12.5"},
            team=self.team,
            timestamp=now - timedelta(days=1),
            properties={"$feature_flag": "typed-flag", "source": "events", "amount": "12.5"},
        )
        _create_flag_evaluations(
            self.team.pk,
            "typed-flag",
            timestamp=now - timedelta(days=1),
            distinct_id="typed",
            person_id=person.uuid,
            person_properties={"amount": "12.5"},
            properties={"source": "flag_evaluations", "amount": "12.5"},
        )
        flush_persons_and_events()
        amount = "properties.amount" if kind == PropertyDefinition.Type.EVENT else "person.properties.amount"

        # Compared as text, "20" and "12.5" sort before "9", so a raw read in any branch or above it drops them.
        response = self._run(
            f"SELECT event, properties.source, toFloatOrZero({amount}) FROM events "
            f"WHERE {MIXED} AND distinct_id = 'typed' AND {amount} > 9 ORDER BY event",
            mode,
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
        )

        assert response.results == [("$feature_flag_called", "flag_evaluations", 12.5), ("$pageview", None, 20.0)]

    @parameterized.expand(
        [
            ("mode_1", FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
            ("mode_2", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY),
        ]
    )
    def test_fields_of_one_name_on_events_and_person_return_their_own_values(
        self, _name: str, mode: FlagEvaluationsMode
    ):
        response = self._run(
            f"SELECT event, properties.source, person.properties.email, properties, person.properties, created_at, "
            f"person.created_at FROM events WHERE {MIXED} AND distinct_id = 'recent' "
            "AND timestamp >= now() - INTERVAL 5 DAY ORDER BY event",
            mode,
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
        )

        flag_call, pageview = response.results
        assert flag_call[:3] == ("$feature_flag_called", "flag_evaluations", "r@x.com")
        assert json.loads(flag_call[3])["source"] == "flag_evaluations"
        assert json.loads(flag_call[4]) == {"email": "r@x.com"}
        assert pageview[:3] == ("$pageview", None, "r@x.com")
        assert json.loads(pageview[4]) == {"email": "r@x.com"}
        assert all(row[6] is not None and row[5] != row[6] for row in response.results)

    @parameterized.expand([("read_flag_evaluations", READ), ("flag_evaluations_only", ONLY)])
    def test_json_extract_string_reads_the_raw_json_value(self, _name: str, mode: FlagEvaluationsMode):
        for name, kind in (
            ("probe", PropertyDefinition.Type.EVENT),
            ("amount", PropertyDefinition.Type.EVENT),
            ("probe", PropertyDefinition.Type.PERSON),
        ):
            PropertyDefinition.objects.create(team=self.team, name=name, property_type="Numeric", type=kind)
        now = datetime.now(UTC)
        person = _create_person(distinct_ids=["probe"], team_id=self.team.pk)
        properties = {"probe": "text", "amount": "12.5", "newline": "a\nb", "a": {"b": "nested"}, "a___b": "flat"}
        for event in ("$pageview", "$feature_flag_called"):
            _create_event(
                event=event,
                distinct_id="probe",
                person_id=person.uuid,
                person_properties={"probe": "text"},
                team=self.team,
                timestamp=now - timedelta(days=1),
                properties={"$feature_flag": "probe-flag", "source": "events", **properties},
            )
        _create_flag_evaluations(
            self.team.pk,
            "probe-flag",
            timestamp=now - timedelta(days=1),
            distinct_id="probe",
            person_id=person.uuid,
            person_properties={"probe": "text"},
            properties={"source": "flag_evaluations", **properties},
        )
        flush_persons_and_events()

        def run(alias: str, expressions: str):
            return self._run(
                f"SELECT {alias}.event, {alias}.properties.source, {expressions} FROM events AS {alias} "
                f"WHERE {alias}.{MIXED} AND {alias}.distinct_id = 'probe' ORDER BY {alias}.event",
                mode,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
            ).results

        def rows(*values) -> list[tuple]:
            return [("$feature_flag_called", "flag_evaluations", *values), ("$pageview", "events", *values)]

        # A rewritten read of the flat key `a___b` gets the export name of `properties.a.b`.
        assert run(
            "events",
            "JSONExtractString(properties, 'probe'), toFloatOrZero(JSONExtractString(properties, 'amount')), "
            "JSONExtractString(properties, 'newline'), properties.a.b, JSONExtractString(properties, 'a___b')",
        ) == rows("text", 12.5, "a\nb", "nested", "flat")
        assert run("e", "JSONExtractString(e.properties, 'probe')") == rows("text")
        # The union refuses a query that reads both `properties` and `person.properties`.
        assert run("events", "JSONExtractString(person.properties, 'probe')") == rows("text")

    def test_prewhere_reads_both_tables(self):
        response = self._run(
            f"SELECT count() FROM events PREWHERE {MIXED} WHERE timestamp >= now() - INTERVAL 120 DAY",
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
        )

        assert response.results == [(7,)]

    @parameterized.expand([("json",), ("materialized",)])
    def test_keyless_flag_calls_come_from_events(self, read: str):
        # A materialized $feature_flag column reads an empty string as missing.
        if read == "materialized":
            self.addCleanup(cleanup_materialized_columns)
            materialize("events", "$feature_flag")
        response = self._run(
            f"SELECT distinct_id FROM events WHERE {MIXED} AND event = '$feature_flag_called' "
            "AND timestamp >= now() - INTERVAL 5 DAY ORDER BY distinct_id",
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
        )

        assert response.results == [("empty",), ("missing",), ("number",), ("recent",)]

    @parameterized.expand(
        [
            (
                "pin_of_one_flag_key",
                "SELECT distinct_id, event, properties.source FROM events WHERE event = '$pageview' "
                "OR (event = '$feature_flag_called' AND properties.$feature_flag = 'probe-flag') ORDER BY timestamp",
                [
                    ("old", "$pageview", None),
                    ("old", "$feature_flag_called", "events"),
                    ("recent", "$pageview", None),
                    ("recent", "$feature_flag_called", "flag_evaluations"),
                ],
            ),
            # The OR reads a person property, so no branch can copy it.
            (
                "or_with_a_person_property",
                f"SELECT distinct_id, event, properties.source FROM events WHERE {MIXED} "
                "AND (event = '$pageview' OR person.properties.email = 'r@x.com') "
                "AND timestamp >= now() - INTERVAL 5 DAY ORDER BY timestamp",
                [("recent", "$pageview", None), ("recent", "$feature_flag_called", "flag_evaluations")],
            ),
            (
                "mixed_type_in_that_clickhouse_converts",
                f"SELECT distinct_id, event, properties.source FROM events WHERE {MIXED} AND 1 IN ('1', '2') "
                "AND timestamp >= now() - INTERVAL 5 DAY ORDER BY timestamp, distinct_id",
                [
                    ("recent", "$pageview", None),
                    ("recent", "$feature_flag_called", "flag_evaluations"),
                    ("empty", "$feature_flag_called", "events"),
                    ("missing", "$feature_flag_called", "events"),
                    ("number", "$feature_flag_called", "events"),
                ],
            ),
            (
                "global_join",
                _global_join(
                    "SELECT e.distinct_id, e.event, e.properties.source FROM events AS e "
                    "INNER JOIN (SELECT 'recent' AS distinct_id) AS r ON e.distinct_id = r.distinct_id "
                    f"WHERE {E_MIXED} AND e.timestamp >= now() - INTERVAL 5 DAY ORDER BY e.timestamp"
                ),
                [("recent", "$pageview", None), ("recent", "$feature_flag_called", "flag_evaluations")],
            ),
        ]
    )
    def test_branch_filters_keep_every_row_the_query_keeps(
        self, _name: str, query: str | ast.SelectQuery, expected: list[tuple]
    ):
        response = self._run(
            query,
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
            PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
        )

        assert response.results == expected

    def test_exception_values_read_as_an_array(self):
        query = f"SELECT count() FROM events WHERE {MIXED} AND has(properties.$exception_values, 'probe')"

        assert self._run(query, FlagEvaluationsMode.READ_FLAG_EVALUATIONS).results == [(0,)]

    @parameterized.expand(
        [
            (
                "scan",
                "SELECT event, toJSONString(properties.probe), properties.probe = 'text' FROM events "
                f"WHERE {MIXED} AND distinct_id = 'json' ORDER BY timestamp, event",
            ),
            (
                "alias",
                "SELECT e.event, toJSONString(e.properties.probe), e.properties.probe = 'text' FROM events AS e "
                f"WHERE {E_MIXED} AND e.distinct_id = 'json' ORDER BY e.timestamp, e.event",
            ),
            (
                "joined_scan",
                _global_join(
                    "SELECT e.event, toJSONString(e.properties.probe), e.properties.probe = 'text' FROM events AS e "
                    "INNER JOIN (SELECT 'json' AS distinct_id) AS j ON e.distinct_id = j.distinct_id "
                    f"WHERE {E_MIXED} ORDER BY e.timestamp, e.event"
                ),
            ),
            (
                "subquery",
                "SELECT event, json, is_text FROM (SELECT event, timestamp, toJSONString(properties.probe) AS json, "
                f"properties.probe = 'text' AS is_text FROM events WHERE {MIXED} AND distinct_id = 'json') "
                "ORDER BY timestamp, event",
            ),
            # The person join reads its key from a second scan of the union, which the serialized read passes through.
            param(
                "person_join",
                "SELECT event, toJSONString(properties.probe), properties.probe = 'text' FROM events "
                f"WHERE {MIXED} AND distinct_id = 'json' ORDER BY timestamp, event, person.id",
                persons_on_events=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            ),
            # Each branch copies the filter, so the flag_evaluations branch has to serialize the key as events does.
            param(
                "filter",
                "SELECT event, toJSONString(properties.probe), properties.probe = 'text' FROM events "
                f"WHERE {MIXED} AND distinct_id = 'json' AND toJSONString(properties.probe) = '123' "
                "ORDER BY timestamp, event",
                kept=[123],
            ),
            # The read of `probe.json` takes the name that the JSON text of `probe` would otherwise get.
            (
                "export_name_collision",
                "SELECT event, toJSONString(properties.probe), properties.probe = 'text' AND properties.probe.json IS NULL "
                f"FROM events WHERE {MIXED} AND distinct_id = 'json' ORDER BY timestamp, event",
            ),
            (
                "integer_key",
                "SELECT event, toJSONString(properties[1]), properties[1] = 'text' FROM events "
                f"WHERE {MIXED} AND distinct_id = 'json' ORDER BY timestamp, event",
            ),
            # Events reads a temporary key from its own column, which the masked document does not cover.
            param(
                "restricted_temporary_key",
                "SELECT event, toJSONString(properties.$sdk_debug_probe), properties.$sdk_debug_probe = 'text' "
                f"FROM events WHERE {MIXED} AND distinct_id = 'json' ORDER BY timestamp, event",
                restriction="$sdk_debug_probe.hidden",
            ),
        ]
    )
    def test_serialized_property_keeps_its_json_type_on_the_native_events_table(
        self,
        _name: str,
        query: str | ast.SelectQuery,
        persons_on_events: PersonsOnEventsMode | None = None,
        kept: list | None = None,
        restriction: str | None = None,
    ):
        if restriction is not None:
            _restrict(self.organization, self.team, restriction)
        missing = object()
        stored_and_read = [
            (123, 123),
            ({"a": 1}, {"a": 1}),
            ([1, 2], [1, 2]),
            ("text", "text"),
            ({}, None),
            (None, None),
            (missing, None),
        ]
        # The first key makes a read by position differ from a read of the key "1".
        self._create_json_rows(
            [
                {} if stored is missing else {"first": "x", "probe": stored, "1": stored, "$sdk_debug_probe": stored}
                for stored, _ in stored_and_read
            ]
        )

        rows = self._run(query, ONLY, persons_on_events, new_events_schema=True).results

        # The two tables format an object's JSON text differently, so the test compares parsed values.
        parsed = [
            (event, text if text in (None, "null") else json.loads(text), is_text) for event, text, is_text in rows
        ]
        assert parsed == [
            (event, read, read == "text")
            for stored, read in stored_and_read
            if kept is None or stored in kept
            for event in ("$feature_flag_called", "$pageview")
        ]

    @parameterized.expand(
        [
            # Events reads a key that a restriction overlaps from the masked document.
            param("restricted_child", "properties.probe", 123, '"123"', restriction="probe.hidden"),
            # Events rebuilds a flag property from `$feature_flags`, which holds text.
            ("flag_property", "properties.`$feature/probe`", 123, '"123"'),
            ("nested_key", "properties.probe.a", {"a": 123}, '"123"'),
            param("legacy_events", "properties.probe", 123, '"123"', new_events_schema=False),
            # Events reads a declared path as its declared type, which is String for `$browser`.
            ("declared_path", "properties.$browser", 123, '"123"'),
            # `toJSONString` of a SELECT alias serializes the text the alias holds, so both rows pass the filter.
            param(
                "select_alias_filter",
                "properties.probe AS p",
                123,
                '"123"',
                where="AND toJSONString(p) = '\"123\"'",
            ),
        ]
    )
    def test_serialized_property_keeps_the_text_events_returns(
        self,
        _name: str,
        read: str,
        stored,
        expected: str,
        restriction: str | None = None,
        new_events_schema: bool = True,
        where: str = "",
    ):
        if restriction is not None:
            _restrict(self.organization, self.team, restriction)
        self._create_json_rows([{"probe": stored, "$feature/probe": stored, "$browser": stored}])

        query = f"SELECT event, toJSONString({read}) FROM events WHERE {MIXED} AND distinct_id = 'json' {where}"
        rows = self._run(query, ONLY, new_events_schema=new_events_schema).results

        assert sorted(rows) == [("$feature_flag_called", expected), ("$pageview", expected)]

    def _create_json_rows(self, rows: list[dict]) -> None:
        start = datetime.now(UTC) - timedelta(hours=len(rows))
        with self.settings(CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA=True):
            for index, properties in enumerate(rows):
                timestamp = start + timedelta(hours=index)
                _create_event(
                    event="$pageview", distinct_id="json", team=self.team, timestamp=timestamp, properties=properties
                )
                _create_flag_evaluations(
                    self.team.pk, "json-flag", timestamp=timestamp, distinct_id="json", properties=properties
                )
            flush_persons_and_events()

    def test_restricted_property_is_hidden_in_every_branch(self):
        _restrict(self.organization, self.team, "source")
        query = f"SELECT properties.source FROM events WHERE {MIXED}"

        assert {row[0] for row in self._run(query, FlagEvaluationsMode.READ_FLAG_EVALUATIONS).results} == {None}
        assert (
            self._run(f"{query} AND properties.source = 'events'", FlagEvaluationsMode.READ_FLAG_EVALUATIONS).results
            == []
        )
        serialized = f"SELECT toJSONString(properties.source) FROM events WHERE {MIXED}"
        assert {row[0] for row in self._run(serialized, ONLY, new_events_schema=True).results} == {None}

    @parameterized.expand(
        [
            (f"{poe.name.lower()}_{'events_json' if new_schema else 'events'}", poe, new_schema)
            for poe in (
                PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS,
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
            )
            for new_schema in (False, True)
        ]
    )
    def test_every_events_field_reads_the_same_type_or_keeps_events(
        self, _name: str, poe: PersonsOnEventsMode, new_schema: bool
    ):
        # The native JSON table reads flag calls as mode 2 does on every mode.
        _set_mode(self.organization, ONLY if new_schema else READ)
        create_group_type_mapping(team=self.team, group_type="organization", group_type_index=0)
        # A typed property reads as a number, which the union keeps only when it converts the read above the branches.
        for property_type in (PropertyDefinition.Type.EVENT, PropertyDefinition.Type.PERSON):
            PropertyDefinition.objects.create(team=self.team, name="probe", property_type="Numeric", type=property_type)
        modifiers = HogQLQueryModifiers(personsOnEventsMode=poe, useNewEventsSchema=new_schema)
        with _enabled_flags(union=True):
            union_database = Database.create_for(team=self.team, modifiers=modifiers)
        with _enabled_flags(union=False):
            events_database = Database.create_for(team=self.team, modifiers=modifiers)

        def sql(query: str, database: Database) -> str:
            context = HogQLContext(
                team_id=self.team.pk, team=self.team, database=database, modifiers=modifiers, enable_select_queries=True
            )
            return prepare_and_print_ast(parse_select(query), context, "clickhouse")[0]

        accepted = []
        for chain in _readable_chains(union_database):
            name = ".".join(f"`{part}`" for part in chain)
            try:
                sql(f"SELECT {name} FROM events", events_database)
            except QueryError:
                continue
            # A field the union cannot read keeps the query on events on mode 1 and fails it on mode 2.
            try:
                union_sql = sql(f"SELECT {name} FROM events WHERE {MIXED}", union_database)
            except QueryError:
                continue
            if "UNION ALL" in union_sql:
                accepted.append(name)

        assert {
            "`timestamp`",
            "`properties`.`probe`",
            "`person_id`",
            "`person`.`properties`.`probe`",
            "`$session_id`",
            "`elements_chain_texts`",
            "`$group_0`",
            # The sessions join reads `$session_id_uuid`, which is not its key.
            "`session`.`id`",
        } <= set(accepted)
        types: dict[bool, dict[str, str]] = {False: {}, True: {}}
        # One query per few fields keeps each union within the memory of a local ClickHouse.
        batches = [accepted[i : i + 8] for i in range(0, len(accepted), 8)]
        for names in batches:
            types_query = f"SELECT {', '.join(f'toTypeName(any({name}))' for name in names)} FROM events WHERE {MIXED}"
            for union in (False, True):
                with _enabled_flags(union=union):
                    response = execute_hogql_query(types_query, team=self.team, modifiers=modifiers)
                types[union].update(zip(names, response.results[0]))

        # flag_evaluations has no elements, and its empty Array(String) widens the union of the events Enum8 array.
        # Comparisons with string literals behave the same on both types.
        widened = {"`elements_chain_elements`": "Array(String)"}
        assert types[True] == {**types[False], **widened}


def _events_schema_for(mode: FlagEvaluationsMode, new_events_schema: bool | None) -> bool | None:
    # The native JSON table reads flag calls as mode 2 does, so a mode 1 case reads the legacy table unless it asks.
    if new_events_schema is None and mode == READ:
        return False
    return new_events_schema


def _readable_chains(database: Database) -> list[list[str | int]]:
    """A chain to select for each events field, and for one field behind each of its joins."""
    events = database.get_table("events")
    chains: list[list[str | int]] = []
    for name, field in events.fields.items():
        if isinstance(field, (LazyJoin, FieldTraverser)):
            chains.extend([[name, "id"], [name, "properties", "probe"], [name, "person_id"]])
            continue
        inner_fields = field.fields.items() if isinstance(field, VirtualTable) else [(None, field)]
        for inner_name, inner in inner_fields:
            chain: list[str | int] = [name] if inner_name is None else [name, inner_name]
            if isinstance(inner, StringJSONDatabaseField):
                chains.append([*chain, "probe"])
            elif isinstance(inner, DatabaseField):
                chains.append(chain)
    return chains
