# The engine isolation gate: every test here runs on SimpleTestCase, where any
# database access raises. This pins the growing set of compile paths that work with
# a fake DataProvider and no Django data — the gate battery expands as more
# mid-compile reads are routed through the provider.
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    HogQLFilters,
    HogQLQueryModifiers,
    HogQLVariable,
    InCohortVia,
    PersonsOnEventsMode,
    RetentionEntity,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.data_provider import (
    ActionRef,
    ActionRefKey,
    CohortRef,
    CohortRefKey,
    InsightVariableInfo,
    MaterializedColumnInfo,
    MaterializedColumnKey,
    PersonWarehousePropertyKey,
    PropertyTypes,
    QueryExpansion,
    StaticDataProvider,
    TextEmbeddingKey,
)
from posthog.hogql.database.database import Database
from posthog.hogql.filters import replace_filters_core
from posthog.hogql.modifiers import create_default_modifiers_for_team_context
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property import apply_path_cleaning_core, entity_to_expr_core, property_to_expr_core
from posthog.hogql.resolver import resolve_types
from posthog.hogql.team_context import HogQLTeamContext
from posthog.hogql.transforms.property_types import build_property_swapper
from posthog.hogql.variables import replace_variables_core

from posthog.models import Property
from posthog.models.property import PropertyType


def _team_context(**overrides: Any) -> HogQLTeamContext:
    defaults: dict[str, Any] = {
        "team_id": 42,
        "project_id": 42,
        "uuid": "018e9a40-0000-0000-0000-000000000000",
        "organization_id": "018e9a40-0000-0000-0000-000000000001",
        "timezone": "US/Pacific",
        "week_start_day": 0,
        "base_currency": "USD",
    }
    defaults.update(overrides)
    return HogQLTeamContext(**defaults)


def _provider(**overrides) -> StaticDataProvider:
    return StaticDataProvider(team_context=_team_context(), **overrides)


class TestEngineIsolationGate(SimpleTestCase):
    def _print_context(self, provider: StaticDataProvider | None = None) -> HogQLContext:
        provider = provider or _provider()
        modifiers = create_default_modifiers_for_team_context(
            provider.team_context,
            HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.DISABLED),
            cloud=False,
        )
        return HogQLContext(
            team_id=provider.team_context.team_id,
            data_provider=provider,
            database=Database(),
            enable_select_queries=True,
            modifiers=modifiers,
        )

    @parameterized.expand(
        [
            ("plain_select", "SELECT event FROM events WHERE timestamp > '2024-01-01'"),
            ("aggregation", "SELECT count(), event FROM events GROUP BY event HAVING count() > 1 LIMIT 10"),
            ("event_properties", "SELECT properties.$browser FROM events"),
            ("person_properties", "SELECT person.properties.email FROM events"),
            ("subquery", "SELECT e FROM (SELECT event AS e FROM events)"),
            ("cte", "WITH top AS (SELECT event, count() AS c FROM events GROUP BY event) SELECT c FROM top"),
            ("session_property", "SELECT session.$session_duration FROM events"),
        ]
    )
    def test_compiles_with_static_provider_and_no_database(self, _name: str, query: str) -> None:
        for dialect in ("hogql", "clickhouse"):
            printed, _ = prepare_and_print_ast(parse_select(query), self._print_context(), dialect=dialect)
            self.assertIsInstance(printed, str)
            self.assertIn("SELECT", printed)

    def test_property_type_catalog_is_fetched_through_the_provider(self) -> None:
        provider = _provider(
            property_type_catalog=PropertyTypes(
                event={"$screen_height": {"type": "Numeric"}},
                person={"is_paying": {"type": "Boolean"}},
            )
        )
        context = self._print_context(provider)
        node = parse_select(
            "SELECT properties.$screen_height, properties.$untyped, person.properties.is_paying FROM events"
        )
        node = resolve_types(node, context, dialect="clickhouse")

        build_property_swapper(node, context)

        assert context.property_swapper is not None
        self.assertEqual(context.property_swapper.event_properties, {"$screen_height": {"type": "Numeric"}})
        self.assertEqual(context.property_swapper.person_properties, {"is_paying": {"type": "Boolean"}})

    def test_materialized_column_resolved_via_provider(self) -> None:
        provider = _provider(
            materialized_columns={
                MaterializedColumnKey("events", "properties", "$browser"): MaterializedColumnInfo(
                    name="mat_$browser", type="String", is_nullable=False
                )
            }
        )
        printed, _ = prepare_and_print_ast(
            parse_select("SELECT properties.$browser FROM events WHERE properties.$browser = 'Chrome'"),
            self._print_context(provider),
            dialect="clickhouse",
        )
        self.assertIn("mat_$browser", printed)
        self.assertNotIn("JSONExtract", printed)

    def test_unmaterialized_property_falls_back_to_json_read(self) -> None:
        printed, _ = prepare_and_print_ast(
            parse_select("SELECT properties.$browser FROM events"),
            self._print_context(),
            dialect="clickhouse",
        )
        self.assertIn("JSONExtract", printed)

    def test_event_property_filter(self) -> None:
        expr = property_to_expr_core(
            Property(type="event", key="$browser", operator="exact", value="Chrome"),
            _provider(),
        )
        self.assertEqual(
            expr,
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", "$browser"]),
                right=ast.Constant(value="Chrome"),
            ),
        )

    def test_warehouse_person_property_bool_coercion_via_provider(self) -> None:
        provider = _provider(
            person_warehouse_property_types={
                PersonWarehousePropertyKey("dw_table", "is_active"): "BooleanDatabaseField"
            }
        )
        expr = property_to_expr_core(
            Property(type="data_warehouse_person_property", key="dw_table.is_active", value="true"),
            provider,
        )
        self.assertEqual(
            expr,
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["person", "dw_table", "is_active"]),
                right=ast.Constant(value=True),
            ),
        )

    @parameterized.expand(
        [
            ("event", "event", "$is_subscribed", None),
            ("person", "person", "is_paying", None),
            ("group", "group", "is_enterprise", 2),
        ]
    )
    def test_bool_coercion_via_provider(
        self, _name: str, kind: PropertyType, key: str, group_type_index: int | None
    ) -> None:
        provider = _provider(
            property_type_catalog=PropertyTypes(
                event={key: {"type": "Boolean"}},
                person={key: {"type": "Boolean"}},
                group={f"{group_type_index}_{key}": {"type": "Boolean"}},
            )
        )
        expr = property_to_expr_core(
            Property(type=kind, key=key, operator="exact", value="true", group_type_index=group_type_index),
            provider,
        )
        assert isinstance(expr, ast.CompareOperation)
        self.assertEqual(expr.right, ast.Constant(value=True))

    def test_cohort_property_filter_via_provider(self) -> None:
        expr = property_to_expr_core(Property(type="cohort", key="id", value=99), _provider(cohort_ids={99: 99}))
        self.assertEqual(
            expr,
            ast.CompareOperation(
                op=ast.CompareOperationOp.InCohort,
                left=ast.Field(chain=["person_id"]),
                right=ast.Constant(value=99),
            ),
        )

    @parameterized.expand([("subquery",), ("leftjoin",), ("leftjoin_conjoined",)])
    def test_in_cohort_compiles_across_modes(self, mode: str) -> None:
        provider = _provider(
            cohort_refs={CohortRefKey("id", 99): [CohortRef(id=99, is_static=False, version=5, name="my cohort")]}
        )
        context = self._print_context(provider)
        context.modifiers.inCohortVia = InCohortVia(mode)
        printed, _ = prepare_and_print_ast(
            parse_select("SELECT event FROM events WHERE person_id IN COHORT 99"), context, dialect="clickhouse"
        )
        self.assertIn("cohort", printed.lower())

    def test_retention_action_entity_via_provider(self) -> None:
        pageview = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value="$pageview"),
        )
        provider = _provider(
            action_refs={ActionRefKey("team", 5): [ActionRef(id=5, name="five")]},
            action_exprs={5: pageview},
        )
        self.assertEqual(entity_to_expr_core(RetentionEntity(id=5, type="actions"), provider), pageview)

    def test_hogqlx_tag_expanded_via_provider(self) -> None:
        from posthog.schema import HogQLQuery

        expansion = parse_select("SELECT event FROM events")
        provider = _provider(query_expansions=[QueryExpansion(HogQLQuery(query="SELECT event FROM events"), expansion)])
        printed, _ = prepare_and_print_ast(
            parse_select("SELECT * FROM <HogQLQuery query='SELECT event FROM events' />"),
            self._print_context(provider),
            dialect="hogql",
        )
        self.assertIn("SELECT event FROM events", printed)

    def test_embed_text_resolved_via_provider(self) -> None:
        provider = _provider(text_embeddings={TextEmbeddingKey("hello", None): [0.25, 0.75]})
        context = self._print_context(provider)
        prepare_and_print_ast(parse_select("SELECT embedText('hello') FROM events"), context, dialect="clickhouse")
        self.assertIn([0.25, 0.75], list(context.values.values()))

    def test_restricted_properties_fetched_via_provider(self) -> None:
        provider = _provider(restricted_properties_set={("secret", 1)})
        context = self._print_context(provider)
        prepare_and_print_ast(parse_select("SELECT event FROM events"), context, dialect="clickhouse")
        self.assertEqual(context.restricted_properties, {("secret", 1)})

    def test_filters_placeholder_resolved_and_printed_via_provider(self) -> None:
        provider = StaticDataProvider(
            team_context=_team_context(
                test_account_filters=[
                    {"key": "email", "type": "person", "value": "posthog.com", "operator": "not_icontains"}
                ]
            )
        )
        node = parse_select("SELECT event FROM events WHERE {filters}")
        replaced = replace_filters_core(
            node,
            HogQLFilters(dateRange=DateRange(date_from="-7d"), filterTestAccounts=True),
            provider,
            Database(),
        )
        printed, _ = prepare_and_print_ast(replaced, self._print_context(provider), dialect="clickhouse")
        self.assertIn("timestamp", printed)
        self.assertIn("email", str(printed))

    def test_variables_substituted_via_provider(self) -> None:
        provider = _provider(
            insight_variables_by_id={"vid-1": InsightVariableInfo(code_name="my_var", default_value=42)}
        )
        node = parse_select("SELECT {variables.my_var} AS v")
        replaced = replace_variables_core(node, [HogQLVariable(variableId="vid-1", code_name="my_var")], provider)
        assert isinstance(replaced, ast.SelectQuery)
        alias = replaced.select[0]
        assert isinstance(alias, ast.Alias)
        self.assertEqual(alias.expr, ast.Constant(value=42))

    def test_relative_date_resolves_against_team_context_timezone(self) -> None:
        expr = property_to_expr_core(
            Property(type="event", key="signup_date", operator="is_date_after", value="-7d"),
            _provider(),
        )
        assert isinstance(expr, ast.CompareOperation)
        self.assertEqual(expr.op, ast.CompareOperationOp.Gt)

    def test_path_cleaning_skips_invalid_filters(self) -> None:
        provider = StaticDataProvider(
            team_context=_team_context(
                path_cleaning_filters=[
                    {"regex": r"/u/\d+", "alias": "/u/:id"},
                    {"not_a_filter": True},
                ]
            )
        )
        cleaned = apply_path_cleaning_core(ast.Constant(value="/u/123"), provider)
        self.assertEqual(
            cleaned,
            ast.Call(
                name="replaceRegexpAll",
                args=[
                    ast.Constant(value="/u/123"),
                    ast.Constant(value=r"/u/\d+"),
                    ast.Constant(value="/u/:id"),
                ],
            ),
        )


class TestContextDataProviderWiring(SimpleTestCase):
    def test_injected_provider_is_used(self) -> None:
        provider = _provider()
        context = HogQLContext(team_id=42, data_provider=provider)
        self.assertIs(context.data, provider)

    def test_defaults_to_django_provider(self) -> None:
        from posthog.hogql_django_provider import DjangoDataProvider

        context = HogQLContext(team_id=42)
        self.assertIsInstance(context.data, DjangoDataProvider)
        self.assertIs(context.data, context.data)
