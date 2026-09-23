from collections.abc import Callable
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import posthoganalytics
from parameterized import parameterized
from posthoganalytics.client import Client
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    AutocompleteCompletionItemKind,
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaPostHogTable,
    DatabaseSchemaQuery,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaSchema,
    DatabaseSchemaSource,
    DatabaseSerializedFieldType,
    DataVisualizationNode,
    HogLanguage,
    HogQLAutocomplete,
    HogQLAutocompleteResponse,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogQLQuery,
    QueryTiming,
)

from posthog.hogql.database.database import Database
from posthog.hogql.database.models import TableNode
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.direct_connection import INVALID_CONNECTION_ID_ERROR
from posthog.hogql.errors import ResolutionError
from posthog.hogql.language_service import (
    CatalogMissing,
    LanguageServiceError,
    LanguageServiceResult,
    MalformedLanguageServiceResponse,
    build_catalog,
)

from posthog.api.services.query import (
    _build_database_schema_query,
    _capture_malformed_language_service_response,
    _DatabaseSchemaCatalog,
    _EditorAssistRoute,
    _language_service_call,
    _record_editor_assist_backend,
    process_query_model,
)
from posthog.constants import AvailableFeature
from posthog.exceptions import DatabaseSchemaUnavailable
from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.data_tools.backend.models.expression import DataWarehouseExpression
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class TestLanguageServiceRouting(SimpleTestCase):
    def test_served_backend_counter_is_exported_for_prometheus(self) -> None:
        labels = {"operation": "metadata", "backend": "python", "reason": "service_error"}
        before = REGISTRY.get_sample_value("hogql_editor_assist_responses_total", labels) or 0

        _record_editor_assist_backend(
            _EditorAssistRoute(enabled=True, result=None, reason="service_error"),
            "metadata",
            "python",
            "service_error",
        )

        assert REGISTRY.get_sample_value("hogql_editor_assist_responses_total", labels) == before + 1
        assert (
            b'hogql_editor_assist_responses_total{backend="python",operation="metadata",reason="service_error"}'
            in generate_latest(
                cast(CollectorRegistry, REGISTRY.restricted_registry(["hogql_editor_assist_responses_total"]))
            )
        )

    @patch("posthog.api.services.query._build_database_schema_query", side_effect=DatabaseSchemaUnavailable())
    @patch("posthog.hogql.language_service.get_client")
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_schema_refresh_failure_falls_back(
        self, client_class: MagicMock, get_redis_client: MagicMock, _build_schema: MagicMock
    ) -> None:
        client = client_class.return_value
        client.base_url = "http://language-service:8091"
        client.validate.side_effect = CatalogMissing("missing")
        get_redis_client.return_value.get.return_value = None
        get_redis_client.return_value.lock.return_value.acquire.return_value = True

        route = _language_service_call(
            cast(Team, SimpleNamespace(pk=12)),
            cast(User, SimpleNamespace(pk=34)),
            HogQLMetadata(query="SELECT event FROM events", language=HogLanguage.HOG_QL),
        )

        assert route.result is None
        assert route.reason == "service_error"

    def test_malformed_response_tracking_uses_sanitized_context(self) -> None:
        sentinel = uuid4().hex
        client = Client("test", send=False, log_captured_exceptions=True, capture_exception_code_variables=True)
        with (
            patch.object(client, "_enqueue", return_value=True) as enqueue,
            patch.object(client.log, "disabled", False),
            patch.object(posthoganalytics, "capture_exception", side_effect=client.capture_exception),
        ):
            with patch.object(client.log, "handle", wraps=client.log.handle) as handle_log:
                with posthoganalytics.new_context(fresh=True):
                    posthoganalytics.tag("query", sentinel)
                    try:
                        raise ValueError(sentinel)
                    except ValueError:
                        pass
                    _capture_malformed_language_service_response("metadata", "response_mapping")

        event = enqueue.call_args.args[0]
        properties = event["properties"]
        exception_values = properties["$exception_list"]
        assert exception_values[0]["value"] == "HogQL language service returned a malformed response"
        assert sentinel not in repr(event)
        records = [call.args[0] for call in handle_log.call_args_list]
        assert records
        assert sentinel not in repr([(record.getMessage(), record.exc_info) for record in records])
        assert all(record.exc_info == (None, None, None) for record in records)
        for exception in exception_values:
            for frame in exception["stacktrace"]["frames"]:
                assert "vars" not in frame
                assert "code_variables" not in frame
        assert {key: properties[key] for key in ("component", "operation", "stage")} == {
            "component": "hogql_language_service",
            "operation": "metadata",
            "stage": "response_mapping",
        }

    @parameterized.expand(
        [
            ("absent", None),
            ("matching", HogQLQuery(query="SELECT * FROM ev")),
            ("stale", HogQLQuery(query="SELECT distinct_id FROM persons LIMIT 5")),
            ("substring", HogQLQuery(query="SELECT * FROM events; SELECT 42")),
        ]
    )
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.api.services.query.LanguageServiceClient")
    @patch("posthog.hogql.timings.perf_counter")
    def test_hogql_autocomplete_uses_language_service_response(
        self,
        _name: str,
        source_query: HogQLQuery | None,
        perf_counter: MagicMock,
        client_class: MagicMock,
        enabled: MagicMock,
        analytics_client: MagicMock,
    ) -> None:
        now = [0.0]
        perf_counter.side_effect = lambda: now[0]

        def enable_language_service(*_args: object, **_kwargs: object) -> bool:
            now[0] += 0.05
            return True

        enabled.side_effect = enable_language_service
        language_result = LanguageServiceResult(
            body={
                "catalogRevision": "warehouse-aliases-v1:cached",
                "suggestions": [
                    {"label": "events", "kind": "table", "detail": "posthog"},
                    {"label": "count", "kind": "function", "insertText": "count()", "sortText": "2-count"},
                    {"label": "=", "kind": "operator", "insertText": "="},
                ],
                "durationMicros": 250,
                "nextCursor": "next",
            },
            duration_seconds=0.001,
            response_size_bytes=128,
        )

        def autocomplete(*_args: object) -> LanguageServiceResult:
            now[0] += 0.4
            return language_result

        client_class.return_value.autocomplete.side_effect = autocomplete

        query = HogQLAutocomplete(
            query="SELECT * FROM ev",
            language=HogLanguage.HOG_QL,
            startPosition=14,
            endPosition=16,
            sourceQuery=source_query,
        )
        original_query = query.model_dump()
        response = process_query_model(
            cast(Team, SimpleNamespace(pk=12, modifiers={})),
            query,
            user=cast(User, SimpleNamespace(pk=34)),
        )

        client_class.return_value.autocomplete.assert_called_once_with(12, 34, query.query, query.endPosition)
        assert query.model_dump() == original_query
        assert isinstance(response, HogQLAutocompleteResponse)
        assert response.suggestions[0].label == "events"
        assert response.suggestions[1].kind == AutocompleteCompletionItemKind.FUNCTION
        assert response.suggestions[1].insertText == "count()"
        assert response.suggestions[1].sortText == "2-count"
        assert response.suggestions[2].kind == AutocompleteCompletionItemKind.OPERATOR
        assert response.incomplete_list is True
        timing_values = {timing.k: timing.t for timing in response.timings or []}
        assert timing_values == {
            "language_service_http": 0.001,
            "language_service_go": 0.00025,
            "./editor_assist/routing": 0.05,
            "./editor_assist/language_service_initial": 0.4,
            "./editor_assist/response_mapping": 0.0,
            "./editor_assist": 0.45,
        }
        analytics_client.labels.assert_called_once_with(
            operation="autocomplete", backend="language_service", reason="served"
        )
        analytics_client.labels.return_value.inc.assert_called_once_with()

    @parameterized.expand([("published", False), ("publication_error", True)])
    def test_cold_autocomplete_reports_catalog_publication_stages(self, _name: str, publication_fails: bool) -> None:
        now = [0.0]
        language_result = LanguageServiceResult(
            body={
                "catalogRevision": "warehouse-aliases-v1:published",
                "suggestions": [],
                "durationMicros": 10_000,
            },
            duration_seconds=0.05,
            response_size_bytes=128,
        )
        client = MagicMock()
        client.base_url = "http://language-service:8091"

        def autocomplete(*_args: object) -> LanguageServiceResult:
            now[0] += 0.1
            if client.autocomplete.call_count < 3:
                raise CatalogMissing("missing")
            return language_result

        def advance(duration: float, result: object = None) -> Callable[..., object]:
            def callback(*_args: object, **_kwargs: object) -> object:
                now[0] += duration
                return result

            return callback

        client.autocomplete.side_effect = autocomplete

        def publish(*_args: object, **_kwargs: object) -> None:
            now[0] += 0.6
            if publication_fails:
                raise LanguageServiceError("unavailable")

        client.publish.side_effect = publish
        redis_client = MagicMock()
        redis_client.get.side_effect = advance(0.02)
        redis_client.lock.return_value.acquire.side_effect = advance(0.3, True)
        redis_client.set.side_effect = advance(0.02)
        redis_client.lock.return_value.release.side_effect = advance(0.01)
        schema_catalog = _DatabaseSchemaCatalog(response=MagicMock(), database=MagicMock())

        python_response = HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        def resolve_database(*_args: object, **_kwargs: object) -> tuple[None, MagicMock]:
            now[0] += 0.3
            return None, MagicMock()

        def autocomplete_in_python(*_args: object, **_kwargs: object) -> HogQLAutocompleteResponse:
            now[0] += 0.4
            return python_response

        with (
            patch("posthog.hogql.timings.perf_counter", side_effect=lambda: now[0]),
            patch("posthog.api.services.query.is_language_service_enabled", return_value=True),
            patch("posthog.api.services.query.LanguageServiceClient", return_value=client),
            patch("posthog.hogql.language_service.get_client", return_value=redis_client),
            patch(
                "posthog.api.services.query._build_database_schema_query",
                side_effect=advance(0.4, schema_catalog),
            ),
            patch("posthog.api.services.query.build_catalog", side_effect=advance(0.5, {"tables": {}})),
            patch("posthog.api.services.query.resolve_database_for_connection", side_effect=resolve_database),
            patch("posthog.api.services.query.get_hogql_autocomplete", side_effect=autocomplete_in_python),
            patch("posthog.api.services.query.create_default_modifiers_for_team", return_value=MagicMock()),
            patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL"),
        ):
            response = process_query_model(
                cast(Team, SimpleNamespace(pk=12, modifiers={})),
                HogQLAutocomplete(
                    query="SELECT * FROM ev",
                    language=HogLanguage.HOG_QL,
                    startPosition=14,
                    endPosition=16,
                ),
                user=cast(User, SimpleNamespace(pk=34)),
            )

        assert isinstance(response, HogQLAutocompleteResponse)
        timing_values = {timing.k: timing.t for timing in response.timings or []}
        if publication_fails:
            assert "language_service_http" not in timing_values
            assert "language_service_go" not in timing_values
        else:
            assert timing_values["language_service_http"] == 0.05
            assert timing_values["language_service_go"] == 0.01
        assert timing_values["./editor_assist/language_service_initial"] == 0.1
        assert timing_values["./editor_assist/catalog_coordination/redis_marker_lookup"] == 0.02
        assert timing_values["./editor_assist/catalog_coordination/redis_lock_acquire"] == 0.3
        assert timing_values["./editor_assist/catalog_coordination/language_service_check"] == (
            0.1 if publication_fails else 0.2
        )
        assert timing_values["./editor_assist/catalog_coordination/catalog_schema"] == 0.4
        assert timing_values["./editor_assist/catalog_coordination/catalog_build"] == 0.5
        assert timing_values["./editor_assist/catalog_coordination/catalog_publish"] == 0.6
        if publication_fails:
            assert "./editor_assist/catalog_coordination/redis_marker_write" not in timing_values
            assert timing_values["./editor_assist/fallback_database"] == 0.3
            assert timing_values["./editor_assist/fallback_python_autocomplete"] == 0.4
        else:
            assert timing_values["./editor_assist/catalog_coordination/redis_marker_write"] == 0.02
        assert timing_values["./editor_assist/catalog_coordination/redis_lock_release"] == 0.01
        assert timing_values["./editor_assist/catalog_coordination"] == (1.93 if publication_fails else 2.05)
        assert timing_values["./editor_assist"] == (2.73 if publication_fails else 2.15)

    @parameterized.expand(
        [
            ("without_source", None, False),
            ("with_stale_source", HogQLQuery(query="SELECT event FROM events WHERE"), False),
            ("with_stale_source_and_indexes", HogQLQuery(query="SELECT event FROM events WHERE"), True),
        ]
    )
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_hogql_metadata_with_source_context_uses_language_service_diagnostics(
        self,
        _name: str,
        source_query: HogQLQuery | None,
        index_usage: bool,
        client_class: MagicMock,
        _enabled: MagicMock,
        responses_total: MagicMock,
    ) -> None:
        client_class.return_value.validate.return_value = LanguageServiceResult(
            body={
                "catalogRevision": "warehouse-aliases-v1:cached",
                "valid": False,
                "diagnostics": [
                    {
                        "code": "unknown_table",
                        "message": 'Unknown table "evnts"',
                        "start": 14,
                        "end": 19,
                        "suggestions": [{"label": "events", "distance": 1}],
                    }
                ],
                "tableNames": ["evnts"],
            },
            duration_seconds=0.001,
            response_size_bytes=128,
        )

        query = HogQLMetadata(
            query="SELECT * FROM evnts",
            language=HogLanguage.HOG_QL,
            sourceQuery=source_query,
            indexUsage=index_usage,
        )
        original_query = query.model_dump()
        response = process_query_model(
            cast(Team, SimpleNamespace(pk=12)),
            query,
            user=cast(User, SimpleNamespace(pk=34)),
        )

        client_class.return_value.validate.assert_called_once_with(12, 34, query.query)
        assert query.model_dump() == original_query
        assert isinstance(response, HogQLMetadataResponse)
        assert response.isValid is False
        assert response.errors[0].message == 'Unknown table "evnts"'
        assert response.errors[0].fix == "events"
        assert response.query == query.query
        assert response.table_names == ["evnts"]
        assert response.index_usage is None
        assert response.isUsingIndices is None
        assert "timings" not in response.model_dump()
        responses_total.labels.assert_called_once_with(
            operation="metadata", backend="language_service", reason="served"
        )
        responses_total.labels.return_value.inc.assert_called_once_with()

    @parameterized.expand(
        [
            ("service_error", LanguageServiceError("unavailable"), "service_error", None),
            (
                "invalid_http",
                MalformedLanguageServiceResponse("malformed"),
                "invalid_response",
                "http_response",
            ),
        ]
    )
    @patch("posthog.api.services.query._capture_malformed_language_service_response")
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.get_hogql_metadata")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_metadata_fallback_records_the_serving_backend_once(
        self,
        _name: str,
        failure: Exception,
        reason: str,
        malformed_stage: str | None,
        client_class: MagicMock,
        enabled: MagicMock,
        python_metadata: MagicMock,
        analytics_client: MagicMock,
        capture_malformed: MagicMock,
    ) -> None:
        client_class.return_value.validate.side_effect = failure
        python_metadata.return_value = HogQLMetadataResponse(
            isValid=True,
            query="SELECT event FROM events",
            errors=[],
            warnings=[],
            notices=[],
            table_names=["events"],
        )

        query = HogQLMetadata(
            query="SELECT event FROM events",
            language=HogLanguage.HOG_QL,
            sourceQuery=HogQLQuery(query="SELECT distinct_id FROM events"),
            indexUsage=True,
        )
        original_query = query.model_dump()
        response = process_query_model(
            cast(Team, SimpleNamespace(pk=12)),
            query,
            user=cast(User, SimpleNamespace(pk=34)),
        )

        assert response is python_metadata.return_value
        assert python_metadata.call_args.kwargs["query"] is query
        assert query.model_dump() == original_query
        client_class.return_value.validate.assert_called_once_with(12, 34, query.query)
        analytics_client.labels.assert_called_once_with(operation="metadata", backend="python", reason=reason)
        analytics_client.labels.return_value.inc.assert_called_once_with()
        enabled.assert_called_once()
        if malformed_stage is None:
            capture_malformed.assert_not_called()
        else:
            capture_malformed.assert_called_once_with("metadata", malformed_stage)

    @parameterized.expand([("collection", {}), ("nested", [None])])
    @patch("posthog.api.services.query._capture_malformed_language_service_response")
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.get_hogql_metadata")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_malformed_metadata_mapping_falls_back(
        self,
        _name: str,
        diagnostics: object,
        client_class: MagicMock,
        enabled: MagicMock,
        python_metadata: MagicMock,
        analytics_client: MagicMock,
        capture_malformed: MagicMock,
    ) -> None:
        client_class.return_value.validate.return_value = LanguageServiceResult(
            body={"catalogRevision": "warehouse-aliases-v1:cached", "diagnostics": diagnostics},
            duration_seconds=0,
            response_size_bytes=0,
        )
        python_metadata.return_value = HogQLMetadataResponse(
            isValid=True,
            query="SELECT event FROM events",
            errors=[],
            warnings=[],
            notices=[],
            table_names=["events"],
        )

        response = process_query_model(
            cast(Team, SimpleNamespace(pk=12)),
            HogQLMetadata(query="SELECT event FROM events", language=HogLanguage.HOG_QL),
            user=cast(User, SimpleNamespace(pk=34)),
        )

        assert response is python_metadata.return_value
        capture_malformed.assert_called_once_with("metadata", "response_mapping")
        analytics_client.labels.assert_called_once_with(
            operation="metadata", backend="python", reason="invalid_response"
        )
        analytics_client.labels.return_value.inc.assert_called_once_with()
        enabled.assert_called_once()

    @parameterized.expand(
        [
            ("collection", {}, "invalid_response"),
            ("nested", [None], "invalid_response"),
            ("unavailable", [], "service_error"),
        ]
    )
    @patch("posthog.api.services.query._capture_malformed_language_service_response")
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.create_default_modifiers_for_team", return_value=MagicMock())
    @patch("posthog.api.services.query.resolve_database_for_connection", return_value=(None, MagicMock()))
    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.api.services.query.LanguageServiceClient")
    @patch("posthog.hogql.timings.perf_counter")
    def test_autocomplete_failure_preserves_source_context_on_fallback(
        self,
        _name: str,
        suggestions: object,
        reason: str,
        perf_counter: MagicMock,
        client_class: MagicMock,
        _enabled: MagicMock,
        python_autocomplete: MagicMock,
        _resolve_database: MagicMock,
        _modifiers: MagicMock,
        analytics_client: MagicMock,
        capture_malformed: MagicMock,
    ) -> None:
        now = [0.0]
        perf_counter.side_effect = lambda: now[0]
        language_result = LanguageServiceResult(
            body={
                "catalogRevision": "warehouse-aliases-v1:cached",
                "suggestions": suggestions,
                "durationMicros": 1,
            },
            duration_seconds=0,
            response_size_bytes=0,
        )

        def autocomplete(*_args: object) -> LanguageServiceResult:
            now[0] += 0.2
            if reason == "service_error":
                raise LanguageServiceError("unavailable")
            return language_result

        def resolve_database(*_args: object, **_kwargs: object) -> tuple[None, MagicMock]:
            now[0] += 0.3
            return None, MagicMock()

        python_response = HogQLAutocompleteResponse(
            suggestions=[],
            incomplete_list=False,
            timings=[QueryTiming(k="./parse_select", t=0.15)],
        )

        def autocomplete_in_python(*_args: object, **_kwargs: object) -> HogQLAutocompleteResponse:
            now[0] += 0.4
            return python_response

        def capture_error(*_args: object, **_kwargs: object) -> None:
            now[0] += 0.1

        client_class.return_value.autocomplete.side_effect = autocomplete
        _resolve_database.side_effect = resolve_database
        python_autocomplete.side_effect = autocomplete_in_python
        capture_malformed.side_effect = capture_error

        query = HogQLAutocomplete(
            query="SELECT event FROM events",
            language=HogLanguage.HOG_QL,
            startPosition=6,
            endPosition=6,
            sourceQuery=HogQLQuery(query="SELECT distinct_id FROM persons LIMIT 5"),
        )
        original_query = query.model_dump()
        response = process_query_model(
            cast(Team, SimpleNamespace(pk=12, modifiers={})),
            query,
            user=cast(User, SimpleNamespace(pk=34)),
        )

        assert response is python_response
        assert python_autocomplete.call_args.kwargs["query"] is query
        assert query.model_dump() == original_query
        client_class.return_value.autocomplete.assert_called_once_with(12, 34, query.query, query.endPosition)
        if reason == "invalid_response":
            capture_malformed.assert_called_once_with("autocomplete", "response_mapping")
        else:
            capture_malformed.assert_not_called()
        analytics_client.labels.assert_called_once_with(operation="autocomplete", backend="python", reason=reason)
        analytics_client.labels.return_value.inc.assert_called_once_with()
        timing_values = {timing.k: timing.t for timing in response.timings or []}
        assert timing_values["./parse_select"] == 0.15
        assert timing_values["./editor_assist/language_service_initial"] == 0.2
        assert timing_values["./editor_assist/fallback_database"] == 0.3
        assert timing_values["./editor_assist/fallback_python_autocomplete"] == 0.4
        if reason == "invalid_response":
            assert timing_values["./editor_assist/fallback_error_tracking"] == 0.1
            assert timing_values["./editor_assist"] == 1.0
        else:
            assert "./editor_assist/fallback_error_tracking" not in timing_values
            assert timing_values["./editor_assist"] == 0.9

    @parameterized.expand(
        [
            ("expression", {"language": "hogQLExpr"}, True),
            ("non_sql_source", {"sourceQuery": {"kind": "EventsNode"}}, True),
            ("connection", {"connectionId": "example-connection"}, True),
            ("globals", {"globals": {}}, True),
            ("filters", {"filters": {}}, True),
            ("modifiers", {"modifiers": {}}, True),
            ("hog", {"language": "hog", "globals": {"event": {}}}, False),
            ("hog_template", {"language": "hogTemplate", "globals": {"event": {}}}, False),
            ("liquid", {"language": "liquid", "globals": {"event": {}}}, False),
            ("hog_json", {"language": "hogJson", "globals": {"event": {}}}, False),
        ]
    )
    @patch("posthog.api.services.query.create_default_modifiers_for_team")
    @patch("posthog.api.services.query.resolve_database_for_connection", return_value=(None, MagicMock()))
    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_context_dependent_autocomplete_uses_python(
        self,
        _name: str,
        context: dict[str, object],
        builds_database: bool,
        client_class: MagicMock,
        _enabled: MagicMock,
        python_autocomplete: MagicMock,
        resolve_database: MagicMock,
        _modifiers: MagicMock,
    ) -> None:
        query = HogQLAutocomplete.model_validate(
            {
                "query": "SELECT event FROM events",
                "language": "hogQL",
                "startPosition": 6,
                "endPosition": 6,
                "sourceQuery": {"kind": "HogQLQuery", "query": "SELECT distinct_id FROM persons"},
                **context,
            }
        )
        python_autocomplete.return_value = HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        response = process_query_model(
            cast(Team, SimpleNamespace(pk=12, modifiers={})),
            query,
            user=cast(User, SimpleNamespace(pk=34)),
        )

        assert response is python_autocomplete.return_value
        assert python_autocomplete.call_args.kwargs["query"] is query
        client_class.assert_not_called()
        timing_values = {timing.k: timing.t for timing in response.timings or []}
        assert "./editor_assist/routing" in timing_values
        assert resolve_database.called is builds_database
        assert (python_autocomplete.call_args.kwargs["database_arg"] is None) is not builds_database
        assert ("./editor_assist/fallback_database" in timing_values) is builds_database
        assert "./editor_assist/fallback_python_autocomplete" in timing_values
        assert "./editor_assist" in timing_values

    @patch("posthog.api.services.query.posthoganalytics.capture_exception", side_effect=RuntimeError("tracking failed"))
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.get_hogql_metadata")
    @patch("posthog.api.services.query._route_editor_assist")
    def test_telemetry_failures_do_not_prevent_python_fallback(
        self,
        route: MagicMock,
        python_metadata: MagicMock,
        analytics_client: MagicMock,
        _capture: MagicMock,
    ) -> None:
        route.return_value = _EditorAssistRoute(
            enabled=True,
            result=LanguageServiceResult(body={"diagnostics": {}}, duration_seconds=0, response_size_bytes=0),
            reason="served",
        )
        python_metadata.return_value = HogQLMetadataResponse(
            isValid=True,
            query="SELECT event FROM events",
            errors=[],
            warnings=[],
            notices=[],
            table_names=["events"],
        )
        analytics_client.labels.return_value.inc.side_effect = RuntimeError("metrics failed")

        response = process_query_model(
            cast(Team, SimpleNamespace(pk=12)),
            HogQLMetadata(query="SELECT event FROM events", language=HogLanguage.HOG_QL),
            user=cast(User, SimpleNamespace(pk=34)),
        )

        assert response is python_metadata.return_value

    @parameterized.expand([("disabled", False, object()), ("no_user", True, None)])
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.get_hogql_metadata")
    @patch("posthog.api.services.query.is_language_service_enabled")
    def test_metadata_metric_excludes_requests_outside_the_enabled_denominator(
        self,
        _name: str,
        flag_enabled: bool,
        user: object | None,
        enabled: MagicMock,
        python_metadata: MagicMock,
        analytics_client: MagicMock,
    ) -> None:
        enabled.return_value = flag_enabled
        python_metadata.return_value = HogQLMetadataResponse(
            isValid=True,
            query="SELECT event FROM events",
            errors=[],
            warnings=[],
            notices=[],
            table_names=["events"],
        )

        process_query_model(
            cast(Team, SimpleNamespace()),
            HogQLMetadata(query="SELECT event FROM events", language=HogLanguage.HOG_QL),
            user=cast(User | None, user),
        )

        analytics_client.labels.assert_not_called()
        if user is None:
            enabled.assert_not_called()
        else:
            enabled.assert_called_once()

    @parameterized.expand(
        [
            ("debug", {"debug": True}),
            (
                "expression",
                {
                    "language": "hogQLExpr",
                    "sourceQuery": {"kind": "HogQLQuery", "query": "SELECT event FROM events"},
                },
            ),
            ("non_sql_source", {"sourceQuery": {"kind": "EventsNode"}}),
            ("variables", {"variables": {}}),
        ]
    )
    @patch("posthog.api.services.query.LanguageServiceClient")
    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.get_hogql_metadata")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    def test_ineligible_metadata_records_python_backend(
        self,
        _name: str,
        context: dict[str, object],
        enabled: MagicMock,
        python_metadata: MagicMock,
        analytics_client: MagicMock,
        client_class: MagicMock,
    ) -> None:
        python_metadata.return_value = HogQLMetadataResponse(
            isValid=True,
            query="SELECT event FROM events",
            errors=[],
            warnings=[],
            notices=[],
            table_names=["events"],
        )

        process_query_model(
            cast(Team, SimpleNamespace()),
            HogQLMetadata.model_validate({"query": "SELECT event FROM events", "language": "hogQL", **context}),
            user=cast(User, SimpleNamespace()),
        )

        analytics_client.labels.assert_called_once_with(operation="metadata", backend="python", reason="ineligible")
        client_class.assert_not_called()
        analytics_client.labels.return_value.inc.assert_called_once_with()
        enabled.assert_called_once()

    @patch("posthog.api.services.query.EDITOR_ASSIST_RESPONSES_TOTAL")
    @patch("posthog.api.services.query.get_hogql_metadata", side_effect=RuntimeError("failed"))
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    def test_failed_python_fallback_does_not_record_a_serving_backend(
        self, _enabled: MagicMock, _python_metadata: MagicMock, analytics_client: MagicMock
    ) -> None:
        with self.assertRaises(RuntimeError):
            process_query_model(
                cast(Team, SimpleNamespace()),
                HogQLMetadata(query="SELECT event FROM events", language=HogLanguage.HOG_QL, debug=True),
                user=cast(User, SimpleNamespace()),
            )

        analytics_client.labels.assert_not_called()

    @patch("posthog.api.services.query._route_editor_assist")
    def test_unknown_properties_remain_warnings(self, mock_language_service_call: MagicMock) -> None:
        mock_language_service_call.return_value = _EditorAssistRoute(
            enabled=True,
            reason="served",
            result=LanguageServiceResult(
                body={
                    "valid": False,
                    "diagnostics": [
                        {
                            "code": "unknown_property",
                            "message": 'Unknown property "missing"',
                            "start": 7,
                            "end": 14,
                        }
                    ],
                    "tableNames": ["events"],
                },
                duration_seconds=0.001,
                response_size_bytes=128,
            ),
        )

        response = process_query_model(
            cast(Team, SimpleNamespace()),
            HogQLMetadata(query="SELECT missing FROM events", language=HogLanguage.HOG_QL),
            user=cast(User, SimpleNamespace()),
        )

        assert isinstance(response, HogQLMetadataResponse)
        assert response.isValid is True
        assert response.errors == []
        assert response.warnings[0].message == 'Unknown property "missing"'

    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.hogql.language_service.get_client")
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_accepts_a_cached_alias_catalog(
        self,
        client_class: MagicMock,
        get_redis_client: MagicMock,
        _enabled: MagicMock,
    ) -> None:
        client_class.return_value.validate.return_value = LanguageServiceResult(
            body={"valid": True, "catalogRevision": "warehouse-aliases-v1:cached"},
            duration_seconds=0,
            response_size_bytes=0,
        )

        result = _language_service_call(
            cast(Team, SimpleNamespace(pk=12)),
            cast(User, SimpleNamespace(pk=34)),
            HogQLMetadata(query="SELECT 1", language=HogLanguage.HOG_QL),
        )

        assert result.result is not None
        get_redis_client.assert_not_called()
        client_class.return_value.publish.assert_not_called()

    @parameterized.expand(
        [
            ("legacy-v1:cached",),
            ("1789766573113832612",),
            (None,),
        ]
    )
    @patch("posthog.api.services.query.build_catalog", return_value={"tables": {}, "properties": {}})
    @patch("posthog.api.services.query._build_database_schema_query")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.hogql.language_service.get_client")
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_refreshes_a_missing_or_legacy_catalog_once(
        self,
        cached_revision: str | None,
        client_class: MagicMock,
        get_redis_client: MagicMock,
        _enabled: MagicMock,
        build_schema: MagicMock,
        build_catalog_mock: MagicMock,
    ) -> None:
        client = client_class.return_value
        client.base_url = "http://language-service:8091"
        get_redis_client.return_value.get.return_value = None
        get_redis_client.return_value.lock.return_value.acquire.return_value = True
        first = (
            CatalogMissing("missing")
            if cached_revision is None
            else LanguageServiceResult(
                body={"valid": True, "catalogRevision": cached_revision}, duration_seconds=0, response_size_bytes=0
            )
        )
        published_revision: list[str] = []

        def publish(_team_id: int, _user_id: int, revision: str, _catalog: dict[str, object]) -> None:
            published_revision.append(revision)

        client.publish.side_effect = publish

        def validate(*_args: object) -> LanguageServiceResult:
            if client.validate.call_count <= 2:
                if isinstance(first, Exception):
                    raise first
                return first
            return LanguageServiceResult(
                body={"valid": True, "catalogRevision": published_revision[0]},
                duration_seconds=0,
                response_size_bytes=0,
            )

        client.validate.side_effect = validate
        build_schema.return_value = _DatabaseSchemaCatalog(response=MagicMock(), database=MagicMock())

        result = _language_service_call(
            cast(Team, SimpleNamespace(pk=12)),
            cast(User, SimpleNamespace(pk=34)),
            HogQLMetadata(query="SELECT 1", language=HogLanguage.HOG_QL),
        )

        assert result.result is not None
        assert published_revision[0].startswith("warehouse-aliases-v1:")
        assert client.validate.call_count == 3
        assert build_catalog_mock.call_args.kwargs["database"] is build_schema.return_value.database

    @patch("posthog.api.services.query.build_catalog", return_value={"tableAliases": {"alias": "canonical"}})
    @patch("posthog.api.services.query._build_database_schema_query")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.hogql.language_service.get_client")
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_falls_back_when_alias_publication_is_not_supported(
        self,
        client_class: MagicMock,
        get_redis_client: MagicMock,
        _enabled: MagicMock,
        build_schema: MagicMock,
        _build_catalog: MagicMock,
    ) -> None:
        client = client_class.return_value
        client.base_url = "http://language-service:8091"
        client.validate.return_value = LanguageServiceResult(
            body={"valid": True, "catalogRevision": "legacy-v1:cached"},
            duration_seconds=0,
            response_size_bytes=0,
        )
        client.publish.side_effect = LanguageServiceError("language service returned 400")
        get_redis_client.return_value.get.return_value = None
        get_redis_client.return_value.lock.return_value.acquire.return_value = True
        build_schema.return_value = _DatabaseSchemaCatalog(response=MagicMock(), database=MagicMock())

        result = _language_service_call(
            cast(Team, SimpleNamespace(pk=12)),
            cast(User, SimpleNamespace(pk=34)),
            HogQLMetadata(query="SELECT 1", language=HogLanguage.HOG_QL),
        )

        assert result.result is None
        client_class.return_value.publish.assert_called_once()

    @parameterized.expand(
        [
            ("warehouse-aliases-v1:concurrent", True, "served", None),
            ("legacy-v1:other", False, "invalid_response", "http_response"),
            (None, False, "invalid_response", "http_response"),
            (123, False, "invalid_response", "http_response"),
        ]
    )
    @patch("posthog.api.services.query.build_catalog", return_value={"tables": {}, "properties": {}})
    @patch("posthog.api.services.query._build_database_schema_query")
    @patch("posthog.api.services.query.is_language_service_enabled", return_value=True)
    @patch("posthog.hogql.language_service.get_client")
    @patch("posthog.api.services.query.LanguageServiceClient")
    def test_classifies_the_retry_catalog_revision(
        self,
        retry_revision: object,
        expected_success: bool,
        expected_reason: str,
        expected_malformed_stage: str | None,
        client_class: MagicMock,
        get_redis_client: MagicMock,
        _enabled: MagicMock,
        build_schema: MagicMock,
        _build_catalog: MagicMock,
    ) -> None:
        client = client_class.return_value
        client.base_url = "http://language-service:8091"
        client.validate.side_effect = [
            LanguageServiceResult(
                body={"valid": True, "catalogRevision": "legacy-v1:cached"},
                duration_seconds=0,
                response_size_bytes=0,
            ),
            LanguageServiceResult(
                body={"valid": True, "catalogRevision": "legacy-v1:cached"},
                duration_seconds=0,
                response_size_bytes=0,
            ),
            LanguageServiceResult(
                body={"valid": True, "catalogRevision": retry_revision},
                duration_seconds=0,
                response_size_bytes=0,
            ),
        ]
        get_redis_client.return_value.get.return_value = None
        get_redis_client.return_value.lock.return_value.acquire.return_value = True
        build_schema.return_value = _DatabaseSchemaCatalog(response=MagicMock(), database=MagicMock())

        result = _language_service_call(
            cast(Team, SimpleNamespace(pk=12)),
            cast(User, SimpleNamespace(pk=34)),
            HogQLMetadata(query="SELECT 1", language=HogLanguage.HOG_QL),
        )

        assert (result.result is not None) is expected_success
        assert result.reason == expected_reason
        assert result.malformed_stage == expected_malformed_stage
        client_class.return_value.publish.assert_called_once()
        assert client_class.return_value.validate.call_count == 3


class TestQueryService(APIBaseTest):
    @patch("posthog.hogql.language_service._properties_for_namespace", return_value=[])
    @patch("posthog.hogql.database.database.feature_enabled_or_false", return_value=True)
    def test_alias_publication_uses_the_permission_filtered_database(
        self, _feature_enabled: MagicMock, _properties: MagicMock
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        membership.level = OrganizationMembership.Level.MEMBER
        membership.save()

        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.POSTGRES, prefix="demo"
        )
        allowed = DataWarehouseTable.objects.create(
            team=self.team,
            name="demo_postgres_orders",
            external_data_source=source,
            credential=credential,
            format="Parquet",
            url_pattern="https://example.com/orders/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String"}},
        )
        denied = DataWarehouseTable.objects.create(
            team=self.team,
            name="demo_postgres_private_orders",
            external_data_source=source,
            credential=credential,
            format="Parquet",
            url_pattern="https://example.com/private-orders/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String"}},
        )
        AccessControl.objects.create(
            team=self.team, resource="warehouse_table", resource_id=str(denied.id), access_level="none"
        )

        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_credential = DataWarehouseCredential.objects.create(
            access_key="key", access_secret="secret", team=other_team
        )
        other_source = ExternalDataSource.objects.create(
            team=other_team, source_type=ExternalDataSourceType.POSTGRES, prefix="other"
        )
        DataWarehouseTable.objects.create(
            team=other_team,
            name="other_postgres_orders",
            external_data_source=other_source,
            credential=other_credential,
            format="Parquet",
            url_pattern="https://example.com/other-orders/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String"}},
        )

        schema_catalog = _build_database_schema_query(self.team, DatabaseSchemaQuery(), user=self.user)
        catalog = build_catalog(
            self.team,
            self.user,
            schema_catalog.response,
            database=schema_catalog.database,
        )

        assert catalog["tableAliases"][allowed.name] == "postgres.demo.orders"
        assert denied.name not in catalog["tableAliases"]
        assert "other_postgres_orders" not in catalog["tableAliases"]

    @patch("posthog.api.services.query.get_query_runner_or_none")
    def test_data_visualization_node_surfaces_hogql_resolution_error_without_value_error_context(
        self, mock_get_query_runner_or_none: MagicMock
    ):
        query = DataVisualizationNode(source=HogQLQuery(query="SELECT properties FROM events JOIN persons ON 1 = 1"))
        runner = MagicMock()
        runner.run.side_effect = ResolutionError("Ambiguous query. Found multiple sources for field: properties")
        mock_get_query_runner_or_none.side_effect = [None, runner]

        with self.assertRaises(ResolutionError) as context:
            process_query_model(self.team, query)

        self.assertIn("Ambiguous query. Found multiple sources for field: properties", str(context.exception))
        self.assertIsNone(context.exception.__context__)

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_filters_tables_to_selected_connection(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "selected_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="selected_table_id",
                name="selected_table",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-selected-1",
                    name="selected_table",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            )
        }
        mock_resolve_database_for_connection.return_value = (selected_source, mock_database)

        join_for_selected_source = SimpleNamespace(
            id="1",
            source_table_name="selected_table",
            source_table_key="selected_table.id",
            joining_table_name="selected_table_2",
            joining_table_key="selected_table_2.id",
            field_name="selected_join",
            configuration={},
            created_at=selected_source.created_at,
        )
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([join_for_selected_source])
        mock_join_filter.return_value = mock_join_queryset

        mock_database.serialize.return_value["selected_table_2"] = DatabaseSchemaDataWarehouseTable(
            fields={},
            format="Parquet",
            id="selected_table_2_id",
            name="selected_table_2",
            url_pattern="direct://postgres",
            schema=DatabaseSchemaSchema(
                id="schema-selected-2",
                name="selected_table_2",
                should_sync=True,
                incremental=False,
            ),
            source=DatabaseSchemaSource(
                id=str(selected_source.id),
                status=selected_source.status,
                source_type=selected_source.source_type,
                access_method=selected_source.access_method,
                prefix=selected_source.prefix or "",
            ),
        )

        response = cast(
            DatabaseSchemaQueryResponse,
            process_query_model(
                self.team,
                DatabaseSchemaQuery(connectionId=str(selected_source.id)),
            ),
        )

        self.assertIsInstance(response, DatabaseSchemaQueryResponse)
        self.assertEqual(set(response.tables.keys()), {"selected_table", "selected_table_2"})
        self.assertEqual(len(response.joins), 1)
        self.assertEqual(response.joins[0].field_name, "selected_join")
        mock_filtered_join_queryset.filter.assert_called_once_with(
            source_table_name__in={"selected_table", "selected_table_2"},
            joining_table_name__in={"selected_table", "selected_table_2"},
        )

    def test_database_schema_query_supports_shallow_and_filtered_modes(self):
        full = cast(DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery()))
        shallow = cast(
            DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery(includeFields=False))
        )
        filtered = cast(
            DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery(tables=["events"]))
        )

        assert set(shallow.tables.keys()) == set(full.tables.keys())
        assert all(table.fields == {} for table in shallow.tables.values())
        assert full.tables["events"].fields != {}

        assert set(filtered.tables.keys()) == {"events"}
        assert filtered.tables["events"] == full.tables["events"]

    @parameterized.expand(
        [
            ("dotted", "postgres.shop.orders", None),
            ("alias", "shop_postgres_orders", None),
            ("join", "postgres.shop.orders", "join"),
            ("expression", "postgres.shop.orders", "expression"),
        ]
    )
    def test_filtered_warehouse_schema_preserves_related_fields(
        self, _label: str, requested: str, dependency: str | None
    ) -> None:
        credential = DataWarehouseCredential.objects.create(access_key="key", access_secret="secret", team=self.team)
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.POSTGRES, prefix="shop"
        )
        for name, columns in {
            "customers": ["id"],
            "orders": ["id", "customer_id"],
            "items": ["id", "order_id"],
        }.items():
            DataWarehouseTable.objects.create(
                team=self.team,
                name=f"shop_postgres_{name}",
                external_data_source=source,
                credential=credential,
                format="Parquet",
                url_pattern="https://example.com/data/*",
                columns={column: {"hogql": "StringDatabaseField", "clickhouse": "String"} for column in columns},
            )
        DataWarehouseTable.objects.create(
            team=self.team,
            name="external_lookup",
            credential=credential,
            format="Parquet",
            url_pattern="https://example.com/lookup/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "String"}},
        )
        if dependency == "join":
            DataWarehouseJoin.objects.create(
                team=self.team,
                source_table_name="postgres.shop.orders",
                source_table_key="id",
                joining_table_name="external_lookup",
                joining_table_key="id",
                field_name="lookup",
            )
        elif dependency == "expression":
            DataWarehouseExpression.objects.for_team(self.team.pk).create(
                team_id=self.team.pk,
                table_name="postgres.shop.orders",
                field_name="lookup",
                expression="(SELECT id FROM external_lookup LIMIT 1)",
            )

        full = cast(DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery()))
        filtered = cast(
            DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery(tables=[requested]))
        )

        assert set(filtered.tables) == {"postgres.shop.orders"}
        table = filtered.tables["postgres.shop.orders"]
        assert table == full.tables["postgres.shop.orders"]
        assert table.fields["customer"].fields == ["id", "properties", "orders"]
        assert table.fields["items"].fields == ["id", "order_id", "properties", "order"]
        if dependency:
            assert "lookup" in table.fields

    @parameterized.expand(
        [
            ("resolve", "resolve_database_for_connection"),
            ("serialize", "serialize"),
        ]
    )
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_failure_is_typed_not_a_bare_500(
        self, _label: str, failing_step: str, mock_resolve_database_for_connection: MagicMock
    ):
        if failing_step == "resolve":
            mock_resolve_database_for_connection.side_effect = RuntimeError("boom")
        else:
            mock_database = MagicMock()
            mock_database.serialize.side_effect = RuntimeError("boom")
            mock_resolve_database_for_connection.return_value = (None, mock_database)

        with self.assertRaises(DatabaseSchemaUnavailable) as error:
            process_query_model(self.team, DatabaseSchemaQuery())

        self.assertEqual(error.exception.get_codes(), "database_schema_unavailable")

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_preserves_serialized_join_fields(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "selected_table": DatabaseSchemaDataWarehouseTable(
                fields={
                    "selected_join": DatabaseSchemaField(
                        name="selected_join",
                        hogql_value="selected_join",
                        type=DatabaseSerializedFieldType.LAZY_TABLE,
                        schema_valid=True,
                        table="selected_table_2",
                        fields=["id", "email"],
                        id="selected_join",
                    )
                },
                format="Parquet",
                id="selected_table_id",
                name="selected_table",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-selected",
                    name="selected_table",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            ),
            "selected_table_2": DatabaseSchemaDataWarehouseTable(
                fields={
                    "id": DatabaseSchemaField(
                        name="id",
                        hogql_value="id",
                        type=DatabaseSerializedFieldType.STRING,
                        schema_valid=True,
                    ),
                    "email": DatabaseSchemaField(
                        name="email",
                        hogql_value="email",
                        type=DatabaseSerializedFieldType.STRING,
                        schema_valid=True,
                    ),
                },
                format="Parquet",
                id="selected_table_2_id",
                name="selected_table_2",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-selected-2",
                    name="selected_table_2",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            ),
        }
        mock_resolve_database_for_connection.return_value = (selected_source, mock_database)

        join_for_selected_source = SimpleNamespace(
            id="1",
            source_table_name="selected_table",
            source_table_key="selected_table.id",
            joining_table_name="selected_table_2",
            joining_table_key="selected_table_2.id",
            field_name="selected_join",
            configuration={},
            created_at=selected_source.created_at,
        )
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([join_for_selected_source])
        mock_join_filter.return_value = mock_join_queryset

        response = cast(
            DatabaseSchemaQueryResponse,
            process_query_model(
                self.team,
                DatabaseSchemaQuery(connectionId=str(selected_source.id)),
            ),
        )

        source_table = cast(DatabaseSchemaDataWarehouseTable, response.tables["selected_table"])
        assert "selected_join" in source_table.fields
        join_field = source_table.fields["selected_join"]
        assert join_field.type == DatabaseSerializedFieldType.LAZY_TABLE
        assert join_field.table == "selected_table_2"
        assert join_field.fields == ["id", "email"]

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_direct_connection_only_returns_queriable_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "queriable_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="queriable_table_id",
                name="queriable_table",
                url_pattern="direct://postgres",
                schema=DatabaseSchemaSchema(
                    id="schema-queriable",
                    name="queriable_table",
                    should_sync=True,
                    incremental=False,
                ),
                source=DatabaseSchemaSource(
                    id=str(selected_source.id),
                    status=selected_source.status,
                    source_type=selected_source.source_type,
                    access_method=selected_source.access_method,
                    prefix=selected_source.prefix or "",
                ),
            )
        }
        mock_resolve_database_for_connection.return_value = (selected_source, mock_database)
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([])
        mock_join_filter.return_value = mock_join_queryset

        response = cast(
            DatabaseSchemaQueryResponse,
            process_query_model(
                self.team,
                DatabaseSchemaQuery(connectionId=str(selected_source.id)),
            ),
        )

        self.assertEqual(set(response.tables.keys()), {"queriable_table"})
        mock_filtered_join_queryset.filter.assert_called_once_with(
            source_table_name__in={"queriable_table"},
            joining_table_name__in={"queriable_table"},
        )

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_without_connection_hides_direct_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        database = Database()
        database.tables.add_child(
            TableNode(
                name="events",
                table=PostgresTable(name="events", fields={}, postgres_table_name="events"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database.tables.add_child(
            TableNode(
                name="direct_table",
                table=PostgresTable(
                    name="direct_table",
                    fields={},
                    postgres_table_name="posthog_dashboard",
                ),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database._warehouse_table_names = ["direct_table"]
        database._direct_access_warehouse_table_names = {"direct_table"}
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (None, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("events"))
            self.assertFalse(database_arg.has_table("direct_table"))
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
            ),
        )

        assert isinstance(response, HogQLAutocompleteResponse)
        self.assertEqual(response.suggestions, [])
        self.assertFalse(response.incomplete_list)
        self.assertIsNotNone(response.timings)

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_with_direct_connection_hides_posthog_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        database = Database()
        database.tables.add_child(
            TableNode(
                name="posthog_dashboard",
                table=PostgresTable(name="posthog_dashboard", fields={}, postgres_table_name="posthog_dashboard"),
            )
        )
        database._connection_id = str(source.id)
        database._warehouse_table_names = ["posthog_dashboard"]
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (source, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("posthog_dashboard"))
            self.assertFalse(database_arg.has_table("events"))
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            ),
        )

        assert isinstance(response, HogQLAutocompleteResponse)
        self.assertEqual(response.suggestions, [])
        self.assertFalse(response.incomplete_list)
        self.assertIsNotNone(response.timings)
        self.assertEqual(mock_resolve_database_for_connection.call_args.kwargs["user"], None)
        self.assertEqual(mock_get_hogql_autocomplete.call_args.kwargs["user"], None)

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_with_direct_connection_filters_other_source_tables(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        selected_source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        database = Database()
        database.tables.add_child(
            TableNode(
                name="selected_table",
                table=PostgresTable(name="selected_table", fields={}, postgres_table_name="selected_table"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database._connection_id = str(selected_source.id)
        database._warehouse_table_names = ["selected_table"]
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (selected_source, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("selected_table"))
            self.assertFalse(database_arg.has_table("other_table"))
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(selected_source.id),
            ),
        )

        assert isinstance(response, HogQLAutocompleteResponse)
        self.assertEqual(response.suggestions, [])
        self.assertFalse(response.incomplete_list)
        self.assertIsNotNone(response.timings)
        self.assertEqual(mock_resolve_database_for_connection.call_args.kwargs["user"], None)
        self.assertEqual(mock_get_hogql_autocomplete.call_args.kwargs["user"], None)

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_with_direct_connection_exposes_selected_tables_only(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )

        database = Database()
        database.tables.add_child(
            TableNode(
                name="selected_table",
                table=PostgresTable(name="selected_table", fields={}, postgres_table_name="selected_table"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database.tables.add_child(
            TableNode(
                name="events",
                table=PostgresTable(name="events", fields={}, postgres_table_name="events"),
            ),
            table_conflict_mode="override",
            children_conflict_mode="override",
        )
        database._connection_id = str(source.id)
        database._warehouse_table_names = ["selected_table"]
        database.apply_schema_scope()
        mock_resolve_database_for_connection.return_value = (source, database)

        def _mock_autocomplete(*args, **kwargs):
            database_arg = kwargs["database_arg"]
            self.assertIsNotNone(database_arg)
            self.assertTrue(database_arg.has_table("selected_table"))
            self.assertFalse(database_arg.has_table("events"))
            self.assertEqual(database_arg.get_all_table_names(), ["selected_table"])
            return HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        mock_get_hogql_autocomplete.side_effect = _mock_autocomplete

        response = process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            ),
        )

        assert isinstance(response, HogQLAutocompleteResponse)
        self.assertEqual(response.suggestions, [])
        self.assertFalse(response.incomplete_list)
        self.assertIsNotNone(response.timings)

    @patch("posthog.api.services.query.get_hogql_autocomplete")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_hogql_autocomplete_passes_user_context(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_get_hogql_autocomplete: MagicMock,
    ):
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
        )
        database = Database()
        mock_resolve_database_for_connection.return_value = (source, database)
        mock_get_hogql_autocomplete.return_value = HogQLAutocompleteResponse(suggestions=[], incomplete_list=False)

        process_query_model(
            self.team,
            HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            ),
            user=self.user,
        )

        self.assertEqual(mock_resolve_database_for_connection.call_args.kwargs["user"], self.user)
        self.assertEqual(mock_get_hogql_autocomplete.call_args.kwargs["user"], self.user)

    @parameterized.expand(
        [
            ("autocomplete", HogQLAutocomplete),
            ("schema", DatabaseSchemaQuery),
        ]
    )
    def test_query_service_rejects_soft_deleted_connection_ids(self, _label: str, query_cls):
        query: HogQLAutocomplete | DatabaseSchemaQuery
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            deleted=True,
        )

        if query_cls is HogQLAutocomplete:
            query = HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            )
        else:
            query = DatabaseSchemaQuery(connectionId=str(source.id))

        with self.assertRaises(ValidationError) as error:
            process_query_model(self.team, query)

        self.assertEqual(cast(list[str], error.exception.detail)[0], INVALID_CONNECTION_ID_ERROR)

    @parameterized.expand(
        [
            ("autocomplete", HogQLAutocomplete),
            ("schema", DatabaseSchemaQuery),
        ]
    )
    def test_query_service_rejects_non_direct_connection_ids(self, _label: str, query_cls):
        query: HogQLAutocomplete | DatabaseSchemaQuery
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
            access_method=ExternalDataSource.AccessMethod.WAREHOUSE,
        )

        if query_cls is HogQLAutocomplete:
            query = HogQLAutocomplete(
                kind="HogQLAutocomplete",
                query="SELECT * FROM ",
                language=HogLanguage.HOG_QL,
                startPosition=14,
                endPosition=14,
                connectionId=str(source.id),
            )
        else:
            query = DatabaseSchemaQuery(connectionId=str(source.id))

        with self.assertRaises(ValidationError) as error:
            process_query_model(self.team, query)

        self.assertEqual(cast(list[str], error.exception.detail)[0], INVALID_CONNECTION_ID_ERROR)

    @patch("posthog.api.services.query.DataWarehouseJoin.objects.filter")
    @patch("posthog.api.services.query.resolve_database_for_connection")
    def test_database_schema_query_without_connection_excludes_direct_sources(
        self,
        mock_resolve_database_for_connection: MagicMock,
        mock_join_filter: MagicMock,
    ):
        mock_database = MagicMock()
        mock_database.has_schema_scope.return_value = True
        mock_database.serialize.return_value = {
            "warehouse_table": DatabaseSchemaDataWarehouseTable(
                fields={},
                format="Parquet",
                id="warehouse_table_id",
                name="warehouse_table",
                url_pattern="s3://bucket/path",
                source=DatabaseSchemaSource(
                    id="warehouse-source",
                    status="Completed",
                    source_type="Stripe",
                    access_method="warehouse",
                    prefix="stripe",
                ),
            ),
            "events": DatabaseSchemaPostHogTable(fields={}, id="events", name="events"),
        }
        mock_resolve_database_for_connection.return_value = (None, mock_database)
        mock_join_queryset = MagicMock()
        mock_filtered_join_queryset = MagicMock()
        dangling_direct_join = SimpleNamespace(
            id="1",
            source_table_name="direct_table",
            source_table_key="direct_table.id",
            joining_table_name="warehouse_table",
            joining_table_key="warehouse_table.id",
            field_name="direct_join",
            configuration={},
            created_at=self.team.created_at,
        )
        mock_join_queryset.exclude.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.iterator.return_value = iter([dangling_direct_join])
        mock_filtered_join_queryset.filter.return_value = mock_filtered_join_queryset
        mock_filtered_join_queryset.filter.return_value.iterator.return_value = iter([])
        mock_join_filter.return_value = mock_join_queryset

        response = cast(DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery()))

        self.assertEqual(set(response.tables.keys()), {"warehouse_table", "events"})
        self.assertEqual(response.joins, [])
        mock_filtered_join_queryset.filter.assert_called_once_with(
            source_table_name__in={"warehouse_table", "events"},
            joining_table_name__in={"warehouse_table", "events"},
        )

    def test_database_schema_query_without_connection_preserves_posthog_tables_with_direct_name_collisions(self):
        credentials = DataWarehouseCredential.objects.create(
            access_key="test_key",
            access_secret="test_secret",
            team=self.team,
        )
        source = ExternalDataSource.objects.create(
            source_id="selected-upstream-source",
            connection_id="selected-connection",
            destination_id="destination-1",
            team=self.team,
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            prefix="ph3",
        )
        DataWarehouseTable.objects.create(
            name="events",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        DataWarehouseTable.objects.create(
            name="persons",
            format="Parquet",
            team=self.team,
            credential=credentials,
            external_data_source=source,
            url_pattern="direct://postgres",
            columns={"email": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )

        response = cast(DatabaseSchemaQueryResponse, process_query_model(self.team, DatabaseSchemaQuery()))

        self.assertIsInstance(response.tables["events"], DatabaseSchemaPostHogTable)
        self.assertIsInstance(response.tables["persons"], DatabaseSchemaPostHogTable)
