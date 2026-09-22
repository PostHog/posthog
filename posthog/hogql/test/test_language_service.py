from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import redis
import requests
from parameterized import parameterized

from posthog.schema import DatabaseSchemaDataWarehouseTable, DatabaseSchemaPostHogTable, DatabaseSchemaQueryResponse

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import TableNode
from posthog.hogql.database.s3_table import S3Table
from posthog.hogql.language_service import (
    CatalogMissing,
    LanguageServiceClient,
    LanguageServiceError,
    LanguageServiceResult,
    MalformedLanguageServiceResponse,
    build_catalog,
    coordinate_catalog_publication,
    is_language_service_enabled,
)
from posthog.hogql.timings import HogQLTimings

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

    @parameterized.expand(
        [
            ("invalid_json", requests.JSONDecodeError("invalid", "x", 0)),
            ("list", []),
            ("scalar", "unexpected"),
            ("null", None),
        ]
    )
    @patch("posthog.hogql.language_service.internal_requests.request")
    def test_rejects_malformed_responses(self, _name: str, body: object, request: MagicMock) -> None:
        response = MagicMock(ok=True, content=b"malformed")
        response.json.side_effect = body if isinstance(body, Exception) else None
        if not isinstance(body, Exception):
            response.json.return_value = body
        request.return_value = response

        with self.assertRaises(MalformedLanguageServiceResponse):
            LanguageServiceClient().validate(12, 34, "SELECT event FROM events")

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


class TestCatalogPublicationCoordination(SimpleTestCase):
    result = LanguageServiceResult(
        body={"valid": True, "catalogRevision": "warehouse-aliases-v1:ready"},
        duration_seconds=0,
        response_size_bytes=0,
    )

    @patch("posthog.hogql.language_service.get_client")
    def test_success_marker_reuses_compatible_catalog(self, get_client: MagicMock) -> None:
        redis_client = get_client.return_value
        redis_client.get.return_value = b"1"
        check_catalog = MagicMock(return_value=self.result)
        publish_catalog = MagicMock()

        result = coordinate_catalog_publication(12, 34, "http://language-service:8091", check_catalog, publish_catalog)

        assert result is self.result
        redis_client.lock.assert_not_called()
        publish_catalog.assert_not_called()

    @patch("posthog.hogql.language_service.get_client")
    def test_missing_catalog_overrides_success_marker(self, get_client: MagicMock) -> None:
        redis_client = get_client.return_value
        redis_client.get.return_value = b"1"
        redis_client.lock.return_value.acquire.return_value = True
        check_catalog = MagicMock(side_effect=[None, None, self.result])
        publish_catalog = MagicMock()

        result = coordinate_catalog_publication(12, 34, "http://language-service:8091", check_catalog, publish_catalog)

        assert result is self.result
        publish_catalog.assert_called_once()
        redis_client.lock.assert_called_once_with(
            redis_client.lock.call_args.args[0], timeout=10, blocking_timeout=0.25
        )
        redis_client.set.assert_called_once_with(redis_client.set.call_args.args[0], "1", ex=5)
        redis_client.lock.return_value.release.assert_called_once()

    @patch("posthog.hogql.language_service.get_client")
    def test_winner_rechecks_before_publishing(self, get_client: MagicMock) -> None:
        redis_client = get_client.return_value
        redis_client.get.return_value = None
        redis_client.lock.return_value.acquire.return_value = True
        publish_catalog = MagicMock()

        result = coordinate_catalog_publication(
            12, 34, "http://language-service:8091", MagicMock(return_value=self.result), publish_catalog
        )

        assert result is self.result
        publish_catalog.assert_not_called()
        redis_client.set.assert_not_called()
        redis_client.lock.return_value.release.assert_called_once()

    @parameterized.expand([(True,), (False,)])
    @patch("posthog.hogql.language_service.get_client")
    @patch("posthog.hogql.timings.perf_counter")
    def test_contender_rechecks_without_publishing(
        self, expected_success: bool, perf_counter: MagicMock, get_client: MagicMock
    ) -> None:
        now = [0.0]
        perf_counter.side_effect = lambda: now[0]
        redis_client = get_client.return_value
        redis_client.get.return_value = None

        def fail_to_acquire() -> bool:
            now[0] += 0.25
            return False

        redis_client.lock.return_value.acquire.side_effect = fail_to_acquire
        publish_catalog = MagicMock()
        timings = HogQLTimings()

        def check_catalog() -> LanguageServiceResult | None:
            now[0] += 0.1
            return self.result if expected_success else None

        result = coordinate_catalog_publication(
            12,
            34,
            "http://language-service:8091",
            check_catalog,
            publish_catalog,
            timings=timings,
        )

        assert (result is not None) is expected_success
        publish_catalog.assert_not_called()
        redis_client.lock.return_value.release.assert_not_called()
        timing_values = {timing.k: timing.t for timing in timings.to_list(back_out_stack=False)}
        assert timing_values["./redis_lock_acquire"] == 0.25
        assert "./redis_lock_release" not in timing_values

    @patch("posthog.hogql.language_service.get_client")
    def test_next_request_recovers_after_unavailable_lease(self, get_client: MagicMock) -> None:
        first_lock = MagicMock()
        first_lock.acquire.return_value = False
        second_lock = MagicMock()
        second_lock.acquire.return_value = True
        redis_client = get_client.return_value
        redis_client.get.return_value = None
        redis_client.lock.side_effect = [first_lock, second_lock]
        check_catalog = MagicMock(side_effect=[None, None, self.result])
        publish_catalog = MagicMock()

        first = coordinate_catalog_publication(12, 34, "http://language-service:8091", check_catalog, publish_catalog)
        second = coordinate_catalog_publication(12, 34, "http://language-service:8091", check_catalog, publish_catalog)

        assert first is None
        assert second is self.result
        publish_catalog.assert_called_once()
        second_lock.release.assert_called_once()

    @patch("posthog.hogql.language_service.get_client")
    def test_publication_failure_does_not_write_marker(self, get_client: MagicMock) -> None:
        redis_client = get_client.return_value
        redis_client.get.return_value = None
        redis_client.lock.return_value.acquire.return_value = True
        publish_catalog = MagicMock(side_effect=LanguageServiceError("publish failed"))

        with self.assertRaises(LanguageServiceError):
            coordinate_catalog_publication(
                12, 34, "http://language-service:8091", MagicMock(return_value=None), publish_catalog
            )

        redis_client.set.assert_not_called()
        redis_client.lock.return_value.release.assert_called_once()

    @parameterized.expand([("get",), ("acquire",)])
    @patch("posthog.hogql.language_service.get_client")
    def test_redis_outage_uses_direct_publication(self, failure_stage: str, get_client: MagicMock) -> None:
        if failure_stage == "get":
            get_client.side_effect = redis.exceptions.ConnectionError("unavailable")
        else:
            get_client.return_value.get.return_value = None
            get_client.return_value.lock.return_value.acquire.side_effect = redis.exceptions.ConnectionError(
                "unavailable"
            )
        publish_catalog = MagicMock()

        result = coordinate_catalog_publication(
            12, 34, "http://language-service:8091", MagicMock(return_value=self.result), publish_catalog
        )

        assert result is self.result
        publish_catalog.assert_called_once()

    @patch("posthog.hogql.language_service.get_client")
    def test_late_redis_errors_preserve_successful_publication(self, get_client: MagicMock) -> None:
        redis_client = get_client.return_value
        redis_client.get.return_value = None
        lock = redis_client.lock.return_value
        lock.acquire.return_value = True
        lock.release.side_effect = redis.exceptions.LockNotOwnedError("expired")
        redis_client.set.side_effect = redis.exceptions.ConnectionError("unavailable")
        publish_catalog = MagicMock()

        result = coordinate_catalog_publication(
            12,
            34,
            "http://language-service:8091",
            MagicMock(side_effect=[None, self.result]),
            publish_catalog,
        )

        assert result is self.result
        publish_catalog.assert_called_once()

    @patch("posthog.hogql.language_service.get_client")
    def test_coordination_keys_isolate_principals_and_service_targets(self, get_client: MagicMock) -> None:
        redis_client = get_client.return_value
        redis_client.get.return_value = None
        redis_client.lock.return_value.acquire.return_value = False

        for team_id, user_id, target in (
            (12, 34, "http://language-service-a:8091"),
            (13, 34, "http://language-service-a:8091"),
            (12, 35, "http://language-service-a:8091"),
            (12, 34, "http://language-service-b:8091"),
        ):
            coordinate_catalog_publication(team_id, user_id, target, MagicMock(return_value=None), MagicMock())

        lock_keys = {call.args[0] for call in redis_client.lock.call_args_list}
        assert len(lock_keys) == 4


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

        catalog = build_catalog(MagicMock(), MagicMock(), schema, database=database)

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

        catalog = build_catalog(MagicMock(), MagicMock(), schema, database=database)

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
            )

        alias = S3Table(name="orders_alias", fields={}, url="", table_id="resolver-id")
        schema = self._warehouse_schema({"postgres.demo.orders": ("resolver-id", ["demo_postgres_orders"])})
        with self.assertRaisesRegex(LanguageServiceError, "has no unique visible target"):
            build_catalog(
                MagicMock(),
                MagicMock(),
                schema,
                database=self._database({"postgres.demo.orders": canonical, "demo_postgres_orders": alias}),
            )

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_rejects_hidden_or_ambiguous_alias_targets(self, _properties: MagicMock) -> None:
        orders = S3Table(name="orders", fields={}, url="", table_id="orders-id")
        hidden_database = self._database(
            {"postgres.demo.orders": orders, "demo_postgres_orders": orders}, hidden={"demo_postgres_orders"}
        )
        schema = self._warehouse_schema({"postgres.demo.orders": ("orders-id", ["demo_postgres_orders"])})

        with self.assertRaisesRegex(LanguageServiceError, "is not visible"):
            build_catalog(MagicMock(), MagicMock(), schema, database=hidden_database)

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
            build_catalog(MagicMock(), MagicMock(), ambiguous_schema, database=ambiguous_database)

    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    def test_ignores_builtin_search_metadata_and_identity_aliases(self, _properties: MagicMock) -> None:
        orders = S3Table(name="orders", fields={}, url="", table_id="orders-id")
        database = self._database({"postgres.demo.orders": orders})
        schema = self._warehouse_schema({"postgres.demo.orders": ("orders-id", ["postgres.demo.orders"])})
        schema.tables["events"] = DatabaseSchemaPostHogTable(fields={}, id="events", name="events")

        catalog = build_catalog(MagicMock(), MagicMock(), schema, database=database)

        assert catalog["tableAliases"] == {}
