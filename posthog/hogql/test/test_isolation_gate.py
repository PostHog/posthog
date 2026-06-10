# The engine isolation gate: every test here runs on SimpleTestCase, where any
# database access raises. This pins the growing set of compile paths that work with
# a fake DataProvider and no Django data — the gate battery expands as more
# mid-compile reads are routed through the provider.
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, MaterializationMode, PersonsOnEventsMode, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.data_provider import PropertyTypes, StaticDataProvider
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team_context
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.property import apply_path_cleaning_core, property_to_expr_core
from posthog.hogql.resolver import resolve_types
from posthog.hogql.team_context import HogQLTeamContext
from posthog.hogql.transforms.property_types import build_property_swapper

from posthog.models import Property


def _team_context(**overrides) -> HogQLTeamContext:
    defaults = {
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
            HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.DISABLED,
                # Materialized-column resolution is the one compile read not yet behind
                # the port (sequenced after the printer rearchitecture lands).
                materializationMode=MaterializationMode.DISABLED,
            ),
            cloud=False,
        )
        return HogQLContext(
            team_id=provider.team_context.team_id,
            data_provider=provider,
            database=Database(),
            enable_select_queries=True,
            modifiers=modifiers,
            # Property-level access control is resolved at the Django boundary;
            # engine callers inject the resolved set.
            restricted_properties=set(),
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

    def test_event_property_filter(self) -> None:
        expr = property_to_expr_core(
            Property(type="event", key="$browser", operator=PropertyOperator.EXACT, value="Chrome"),
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
        provider = _provider(person_warehouse_property_types={("dw_table", "is_active"): "BooleanDatabaseField"})
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
    def test_bool_coercion_via_provider(self, _name: str, kind: str, key: str, group_type_index: int | None) -> None:
        provider = _provider(
            property_type_catalog=PropertyTypes(
                event={key: {"type": "Boolean"}},
                person={key: {"type": "Boolean"}},
                group={f"{group_type_index}_{key}": {"type": "Boolean"}},
            )
        )
        expr = property_to_expr_core(
            Property(
                type=kind, key=key, operator=PropertyOperator.EXACT, value="true", group_type_index=group_type_index
            ),
            provider,
        )
        assert isinstance(expr, ast.CompareOperation)
        self.assertEqual(expr.right, ast.Constant(value=True))

    def test_relative_date_resolves_against_team_context_timezone(self) -> None:
        expr = property_to_expr_core(
            Property(type="event", key="signup_date", operator=PropertyOperator.IS_DATE_AFTER, value="-7d"),
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
        from posthog.hogql.django_provider import DjangoDataProvider

        context = HogQLContext(team_id=42)
        self.assertIsInstance(context.data, DjangoDataProvider)
        self.assertIs(context.data, context.data)
