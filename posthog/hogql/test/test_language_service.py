from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests

from posthog.schema import DatabaseSchemaDataWarehouseTable, DatabaseSchemaPostHogTable, DatabaseSchemaQueryResponse

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import TableNode
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.language_service import (
    CatalogMissing,
    LanguageServiceClient,
    LanguageServiceError,
    build_catalog,
    is_language_service_enabled,
)

from posthog.jwt import PosthogJwtAudience, decode_jwt


@override_settings(
    HOGQL_LANGUAGE_SERVICE_URL="http://language-service:8091",
    HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=["test-language-service-signing-key"],
)
class TestLanguageServiceClient(SimpleTestCase):
    @patch("posthog.hogql.language_service.internal_requests.request")
    def test_routes_request_and_scopes_token_to_principal_and_operation(self, request: MagicMock) -> None:
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.content = b'{"valid":true,"diagnostics":[],"durationMicros":42}'
        response.json.return_value = {"valid": True, "diagnostics": [], "durationMicros": 42}
        request.return_value = response

        result = LanguageServiceClient().validate(12, 34, "SELECT 1")

        request.assert_called_once()
        call = request.call_args
        assert call.args == ("POST", "http://language-service:8091/teams/12/users/34/validate")
        assert call.kwargs["json"] == {"query": "SELECT 1"}
        assert call.kwargs["timeout"] == (0.25, 1)
        assert call.kwargs["headers"]["X-HogQL-Affinity-Key"] == (
            "a5c8d54c25064f11498a937f38591eba85a3e67cccc102e6c4f76bbf5377cc37"
        )
        token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = decode_jwt(
            token,
            PosthogJwtAudience.HOGQL_LANGUAGE_SERVICE,
            verification_keys=["test-language-service-signing-key"],
        )
        assert claims["team_id"] == 12
        assert claims["user_id"] == 34
        assert claims["operations"] == ["validate"]
        assert result.body["valid"] is True
        assert result.response_size_bytes == len(response.content)

    @patch("posthog.hogql.language_service.internal_requests.request")
    def test_catalog_miss_has_a_distinct_error(self, request: MagicMock) -> None:
        response = MagicMock()
        response.ok = False
        response.status_code = 404
        response.content = b"catalog not found"
        request.return_value = response

        with self.assertRaises(CatalogMissing):
            LanguageServiceClient().autocomplete(12, 34, "SELECT ", 7)

        assert request.call_args.kwargs["json"] == {
            "query": "SELECT ",
            "position": 7,
            "positionEncoding": "utf-16",
        }

    @patch("posthog.hogql.language_service.LANGUAGE_SERVICE_HTTP_DURATION_SECONDS")
    @patch("posthog.hogql.language_service.internal_requests.request", side_effect=requests.Timeout("timed out"))
    def test_records_latency_for_failed_requests(self, _request: MagicMock, duration: MagicMock) -> None:
        with self.assertRaises(LanguageServiceError):
            LanguageServiceClient().validate(12, 34, "SELECT 1")

        duration.labels.assert_called_once_with(operation="validate")
        duration.labels.return_value.observe.assert_called_once()


class TestLanguageServiceFeatureFlag(SimpleTestCase):
    @override_settings(DEBUG=True, HOGQL_LANGUAGE_SERVICE_URL="", HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=[])
    def test_disabled_without_service_configuration(self) -> None:
        assert not is_language_service_enabled(MagicMock(), MagicMock())

    @override_settings(
        DEBUG=True,
        HOGQL_LANGUAGE_SERVICE_URL="http://language-service:8091",
        HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=["key"],
    )
    def test_enabled_in_debug_with_service_configuration(self) -> None:
        assert is_language_service_enabled(MagicMock(), MagicMock())

    @override_settings(
        DEBUG=False,
        HOGQL_LANGUAGE_SERVICE_URL="http://language-service:8091",
        HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=["key"],
    )
    @patch("posthog.hogql.language_service.posthoganalytics.feature_enabled", return_value=True)
    def test_production_uses_local_feature_flag_evaluation(self, feature_enabled: MagicMock) -> None:
        team = MagicMock(id=12, organization_id=56)
        user = MagicMock(distinct_id="user-distinct-id", email="person@example.com")

        assert is_language_service_enabled(team, user)
        feature_enabled.assert_called_once_with(
            "hogql-language-service",
            "user-distinct-id",
            person_properties={"email": "person@example.com"},
            groups={"organization": "56", "project": "12"},
            group_properties={"organization": {"id": "56"}, "project": {"id": "12"}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )


class TestLanguageServiceCatalog(SimpleTestCase):
    def _database(self, paths: dict[str, S3Table], *, hidden: set[str] | None = None) -> Database:
        database = Database(include_posthog_tables=False)
        for path, table in paths.items():
            node = TableNode.create_nested_for_chain(path.split("."), table)
            if hidden and path in hidden:
                node.hidden = True
            database.tables.add_child(node)
        return database

    def _warehouse_schema(self, tables: dict[str, tuple[str, list[str] | None]]) -> DatabaseSchemaQueryResponse:
        return DatabaseSchemaQueryResponse(
            tables={
                name: DatabaseSchemaDataWarehouseTable(fields={}, id=table_id, name=name, search_aliases=aliases)
                for name, (table_id, aliases) in tables.items()
            },
            joins=[],
        )

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_publishes_only_resolver_confirmed_aliases(self, _properties: MagicMock) -> None:
        orders = S3Table(name="orders", fields={}, url="", table_id="orders-id")
        database = self._database(
            {
                "postgres.demo.orders": orders,
                "demo_postgres_orders": orders,
                "DEMO_POSTGRES_ORDERS": orders,
            }
        )
        schema = self._warehouse_schema(
            {"postgres.demo.orders": ("orders-id", ["demo_postgres_orders", "DEMO_POSTGRES_ORDERS"])}
        )

        catalog = build_catalog(MagicMock(), MagicMock(), schema, database=database, publish_warehouse_aliases=True)

        assert catalog["tableAliases"] == {
            "demo_postgres_orders": "postgres.demo.orders",
            "DEMO_POSTGRES_ORDERS": "postgres.demo.orders",
        }

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_uses_the_resolver_winner_for_colliding_alias_candidates(self, _properties: MagicMock) -> None:
        orders = S3Table(name="orders", fields={}, url="", table_id="orders-id")
        customers = S3Table(name="customers", fields={}, url="", table_id="customers-id")
        database = self._database(
            {
                "postgres.demo.orders": orders,
                "postgres.demo.customers": customers,
                "demo_shared": customers,
            }
        )
        schema = self._warehouse_schema(
            {
                "postgres.demo.orders": ("orders-id", ["demo_shared"]),
                "postgres.demo.customers": ("customers-id", None),
            }
        )

        catalog = build_catalog(MagicMock(), MagicMock(), schema, database=database, publish_warehouse_aliases=True)

        assert catalog["tableAliases"] == {"demo_shared": "postgres.demo.customers"}

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_rejects_mismatched_canonical_and_alias_identities(self, _properties: MagicMock) -> None:
        canonical = S3Table(name="orders", fields={}, url="", table_id="resolver-id")
        schema = self._warehouse_schema({"postgres.demo.orders": ("serialized-id", None)})

        with self.assertRaisesRegex(LanguageServiceError, "does not match the HogQL resolver"):
            build_catalog(
                MagicMock(),
                MagicMock(),
                schema,
                database=self._database({"postgres.demo.orders": canonical}),
                publish_warehouse_aliases=True,
            )

        alias = S3Table(name="orders_alias", fields={}, url="", table_id="resolver-id")
        schema = self._warehouse_schema({"postgres.demo.orders": ("resolver-id", ["demo_postgres_orders"])})
        with self.assertRaisesRegex(LanguageServiceError, "has no unique visible target"):
            build_catalog(
                MagicMock(),
                MagicMock(),
                schema,
                database=self._database({"postgres.demo.orders": canonical, "demo_postgres_orders": alias}),
                publish_warehouse_aliases=True,
            )

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_rejects_hidden_or_ambiguous_alias_targets(self, _properties: MagicMock) -> None:
        orders = S3Table(name="orders", fields={}, url="", table_id="orders-id")
        hidden_database = self._database(
            {"postgres.demo.orders": orders, "demo_postgres_orders": orders}, hidden={"demo_postgres_orders"}
        )
        schema = self._warehouse_schema({"postgres.demo.orders": ("orders-id", ["demo_postgres_orders"])})

        with self.assertRaisesRegex(LanguageServiceError, "is not visible"):
            build_catalog(MagicMock(), MagicMock(), schema, database=hidden_database, publish_warehouse_aliases=True)

        ambiguous_schema = self._warehouse_schema(
            {
                "postgres.demo.orders": ("orders-id", ["demo_postgres_orders"]),
                "postgres.archive.orders": ("orders-id", None),
            }
        )
        ambiguous_database = self._database(
            {
                "postgres.demo.orders": orders,
                "postgres.archive.orders": orders,
                "demo_postgres_orders": orders,
            }
        )
        with self.assertRaisesRegex(LanguageServiceError, "has no unique visible target"):
            build_catalog(
                MagicMock(), MagicMock(), ambiguous_schema, database=ambiguous_database, publish_warehouse_aliases=True
            )

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_ignores_builtin_search_metadata_and_identity_aliases(self, _properties: MagicMock) -> None:
        orders = S3Table(name="orders", fields={}, url="", table_id="orders-id")
        database = self._database({"postgres.demo.orders": orders})
        schema = self._warehouse_schema({"postgres.demo.orders": ("orders-id", ["postgres.demo.orders"])})
        schema.tables["events"] = DatabaseSchemaPostHogTable(fields={}, id="events", name="events")

        catalog = build_catalog(MagicMock(), MagicMock(), schema, database=database, publish_warehouse_aliases=True)

        assert catalog["tableAliases"] == {}

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_omits_alias_contract_when_publication_is_disabled(self, _properties: MagicMock) -> None:
        schema = self._warehouse_schema({"postgres.demo.orders": ("orders-id", ["demo_postgres_orders"])})

        catalog = build_catalog(MagicMock(), MagicMock(), schema)

        assert "tableAliases" not in catalog
