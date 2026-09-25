from uuid import UUID, uuid4

from django.http import QueryDict
from django.test import SimpleTestCase

from parameterized import parameterized

from products.ai_observability.backend.api.offline_experiment_read_serializers import (
    OfflineEmptyQuerySerializer,
    OfflineExperimentQuerySerializer,
    OfflinePageQuerySerializer,
    OfflineResultQuerySerializer,
    OfflineSummaryQuerySerializer,
)
from products.ai_observability.backend.api.offline_experiment_serializers import (
    MAX_ITEM_PAYLOAD_BYTES,
    MAX_JSON_DEPTH,
    MAX_RESULT_PAYLOAD_BYTES,
    ExperimentSubmissionSerializer,
    ItemSubmissionSerializer,
    ResultSubmissionSerializer,
    UploadSubmissionSerializer,
)
from products.ai_observability.backend.offline_evaluation_types import JSONValue, ResultValue

ITEM_ID = UUID("01922222-2222-7222-8222-222222222222")
SCORER_VERSION_ID = UUID("01923333-3333-7333-8333-333333333333")


class TestOfflineReadQuerySerializers(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", OfflineEmptyQuerySerializer, "limit"),
            ("page", OfflinePageQuerySerializer, "scorer_version_ids"),
            ("results", OfflineResultQuerySerializer, "scorer_definition_id"),
            ("summary", OfflineSummaryQuerySerializer, "statuses"),
            ("experiments", OfflineExperimentQuerySerializer, "team_id"),
        ]
    )
    def test_each_surface_rejects_unsupported_filters(
        self,
        _name: str,
        serializer_class: type[OfflineEmptyQuerySerializer] | type[OfflinePageQuerySerializer],
        field: str,
    ) -> None:
        serializer = serializer_class(data={field: "1"})
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    @parameterized.expand(
        [
            ("zero_limit", {"limit": "0"}, "limit"),
            ("oversized_page", {"limit": "101"}, "limit"),
            ("oversized_cursor", {"cursor": "a" * 2049}, "cursor"),
            ("unknown_source", {"run_source": "cron"}, "run_source"),
            ("unknown_status", {"statuses": "complete"}, "statuses"),
            ("duplicate_status", {"statuses": "completed,completed"}, "statuses"),
            (
                "reversed_dates",
                {"date_from": "2026-09-25T10:00:00Z", "date_to": "2026-09-24T10:00:00Z"},
                "date_to",
            ),
            ("invalid_version", {"scorer_version_ids": "not-a-uuid"}, "scorer_version_ids"),
            (
                "duplicate_versions",
                {"scorer_version_ids": f"{SCORER_VERSION_ID},{SCORER_VERSION_ID}"},
                "scorer_version_ids",
            ),
            (
                "oversized_version_selection",
                {"scorer_version_ids": ",".join(str(UUID(int=index + 1)) for index in range(21))},
                "scorer_version_ids",
            ),
        ]
    )
    def test_filters_reject_unbounded_or_ambiguous_queries(self, _name: str, query: dict[str, str], field: str) -> None:
        serializer = OfflineExperimentQuerySerializer(data=query)
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    def test_repeated_query_parameters_are_rejected_instead_of_using_the_last_value(self) -> None:
        serializer = OfflineExperimentQuerySerializer(data=QueryDict("limit=1&limit=100"))
        self.assertFalse(serializer.is_valid())
        self.assertIn("limit", serializer.errors)

    def test_normalizes_supported_filters_and_maximum_version_selection(self) -> None:
        versions = tuple(UUID(int=index + 1) for index in range(20))
        definition_id = uuid4()
        serializer = OfflineExperimentQuerySerializer(
            data={
                "limit": "100",
                "run_source": "not_specified",
                "statuses": "uploading,completed,failed",
                "scorer_definition_id": str(definition_id),
                "scorer_version_ids": ",".join(str(version) for version in versions),
                "date_from": "2026-09-24T10:00:00Z",
                "date_to": "2026-09-25T10:00:00Z",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        query = serializer.validated_data
        self.assertEqual(query.limit, 100)
        self.assertIsNone(query.run_source)
        self.assertTrue(query.run_source_is_null)
        self.assertEqual(query.statuses, ("uploading", "completed", "failed"))
        self.assertEqual(query.scorer_definition_id, definition_id)
        self.assertEqual(query.scorer_version_ids, versions)
        self.assertIsNotNone(query.date_from)
        self.assertIsNotNone(query.date_to)


class TestOfflineExperimentSubmissionSerializers(SimpleTestCase):
    def experiment_data(self, **overrides: object) -> dict[str, object]:
        return {"id": str(uuid4()), "name": "Answer quality", "started_at": "2026-09-24T10:00:00Z", **overrides}

    def result_data(self, **overrides: object) -> dict[str, object]:
        return {
            "item_id": str(ITEM_ID),
            "scorer_version_id": str(SCORER_VERSION_ID),
            "status": "ok",
            "value": True,
            **overrides,
        }

    @parameterized.expand(
        [
            ("run_source", ""),
            ("run_source", "cron"),
            ("suite_key", ""),
            ("suite_key", 12),
            ("name", 12),
            ("name", "\x00"),
            ("model_version", "\ud800"),
            ("expected_item_count", True),
            ("expected_item_count", "10"),
            ("expected_result_count", 1.0),
            ("expected_result_count", -1),
            ("expected_result_count", 2**63),
            ("id", 123),
            ("id", "not-a-uuid"),
            ("dataset_revision_id", 123),
            ("team_id", 1),
            ("submission_fingerprint", "0" * 64),
            ("finished_at", "2026-09-24T10:01:00Z"),
        ]
    )
    def test_experiment_rejects_invalid_or_server_owned_fields(self, field: str, value: object) -> None:
        serializer = ExperimentSubmissionSerializer(data=self.experiment_data(**{field: value}))
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    def test_omitted_and_null_optional_experiment_fields_have_the_same_meaning(self) -> None:
        body = self.experiment_data()
        omitted = ExperimentSubmissionSerializer(data=body)
        explicit = ExperimentSubmissionSerializer(data={**body, "run_source": None, "suite_key": None})
        self.assertTrue(omitted.is_valid(), omitted.errors)
        self.assertTrue(explicit.is_valid(), explicit.errors)
        self.assertEqual(omitted.validated_data, explicit.validated_data)

    @parameterized.expand([(0, 0.0), (1.234567890123, 1.234567890123), (False, False), (["z", "a"], ["a", "z"])])
    def test_result_preserves_score_types_and_normalizes_category_order(
        self, supplied: object, expected: ResultValue
    ) -> None:
        serializer = ResultSubmissionSerializer(data=self.result_data(value=supplied))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data.value, expected)
        self.assertIs(type(serializer.validated_data.value), type(expected))

    @parameterized.expand(
        [
            ("string_number", "0.5"),
            ("string_boolean", "true"),
            ("null", None),
            ("nan", float("nan")),
            ("infinity", float("inf")),
            ("overflow", 10**400),
            ("empty_categories", []),
            ("duplicate_categories", ["a", "a"]),
            ("coerced_categories", [1]),
            ("empty_category", [""]),
            ("long_category", ["a" * 129]),
            ("nul_category", ["\x00"]),
            ("surrogate_category", ["\ud800"]),
            ("object", {}),
        ]
    )
    def test_result_rejects_invalid_score_types(self, _name: str, value: object) -> None:
        serializer = ResultSubmissionSerializer(data=self.result_data(value=value))
        self.assertFalse(serializer.is_valid())
        self.assertIn("value", serializer.errors)

    @parameterized.expand(
        [
            ({"status": "error", "value": 0}, {"value"}),
            ({"status": "skipped", "value": False}, {"value"}),
            ({"status": "not_applicable", "value": ["a"]}, {"value"}),
            ({"error_code": "timeout"}, {"error_code"}),
            ({"payload": {"error_message": "Timed out"}}, {"payload"}),
            ({"id": str(uuid4())}, {"id"}),
            ({"scorer_definition_id": str(uuid4())}, {"scorer_definition_id"}),
            ({"accepted_at": "2026-09-24T10:00:00Z"}, {"accepted_at"}),
            ({"payload_state": "available"}, {"payload_state"}),
            (
                {
                    "status": "skipped",
                    "value": False,
                    "error_code": "timeout",
                    "payload": {"error_message": "Timed out"},
                },
                {"value", "error_code", "payload"},
            ),
        ]
    )
    def test_result_status_invariants_and_server_owned_fields(
        self, overrides: dict[str, object], fields: set[str]
    ) -> None:
        serializer = ResultSubmissionSerializer(data=self.result_data(**overrides))
        self.assertFalse(serializer.is_valid())
        self.assertEqual(set(serializer.errors), fields)

    def test_error_without_score_accepts_error_details(self) -> None:
        data = self.result_data(status="error", error_code="timeout", payload={"error_message": "Timed out"})
        del data["value"]
        serializer = ResultSubmissionSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIsNone(serializer.validated_data.value)

    def test_payload_omission_empty_object_and_null_property_remain_distinct(self) -> None:
        values = []
        payloads: list[dict[str, object]] = [{}, {"payload": {}}, {"payload": {"input": None}}]
        for payload in payloads:
            serializer = ItemSubmissionSerializer(data={"id": str(ITEM_ID), **payload})
            self.assertTrue(serializer.is_valid(), serializer.errors)
            values.append(serializer.validated_data.payload)
        self.assertEqual(values, [None, {}, {"input": None}])

    @parameterized.expand(
        [
            ("null_object", None),
            ("array_object", []),
            ("unknown_property", {"unknown": True}),
            ("metadata_type", {"metadata": []}),
            ("nested_nan", {"input": {"value": float("nan")}}),
            ("nested_nul", {"input": ["\x00"]}),
            ("nul_key", {"input": {"\x00": True}}),
            ("surrogate_value", {"input": "\ud800"}),
            ("surrogate_key", {"input": {"\ud800": None}}),
            ("non_json_value", {"input": {"bytes": b"content"}}),
        ]
    )
    def test_payload_rejects_values_that_cannot_be_safely_stored(self, _name: str, payload: object) -> None:
        serializer = ItemSubmissionSerializer(data={"id": str(ITEM_ID), "payload": payload})
        self.assertFalse(serializer.is_valid())
        self.assertIn("payload", serializer.errors)

    def test_payload_nesting_limit_includes_the_enclosing_object(self) -> None:
        value: JSONValue = None
        for _ in range(MAX_JSON_DEPTH - 1):
            value = [value]
        at_limit = ItemSubmissionSerializer(data={"id": str(ITEM_ID), "payload": {"input": value}})
        self.assertTrue(at_limit.is_valid(), at_limit.errors)
        too_deep = ItemSubmissionSerializer(data={"id": str(ITEM_ID), "payload": {"input": [value]}})
        self.assertFalse(too_deep.is_valid())
        self.assertIn("payload", too_deep.errors)

    def test_payload_limits_count_utf8_bytes_and_apply_separately(self) -> None:
        item = ItemSubmissionSerializer(
            data={"id": str(ITEM_ID), "payload": {"input": "é" * (MAX_ITEM_PAYLOAD_BYTES // 2)}}
        )
        result = ResultSubmissionSerializer(
            data=self.result_data(payload={"reasoning": "a" * MAX_RESULT_PAYLOAD_BYTES})
        )
        for serializer in (item, result):
            self.assertFalse(serializer.is_valid())
            self.assertIn("payload", serializer.errors)

    def test_shared_item_supports_multiple_scorers_and_omitted_declarations(self) -> None:
        serializer = UploadSubmissionSerializer(
            data={
                "items": [{"id": str(ITEM_ID), "payload": {"input": "question", "output": "answer"}}],
                "results": [self.result_data(), self.result_data(scorer_version_id=str(uuid4()))],
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(len(serializer.validated_data.items), 1)
        self.assertEqual(len(serializer.validated_data.results), 2)
        reference = UploadSubmissionSerializer(data={"results": [self.result_data()]})
        self.assertTrue(reference.is_valid(), reference.errors)
        self.assertEqual(reference.validated_data.items, [])

    @parameterized.expand(
        [("duplicate_items", "items"), ("duplicate_results", "results"), ("unreferenced_item", "items")]
    )
    def test_upload_rejects_ambiguous_or_unreferenced_declarations(self, case: str, field: str) -> None:
        data: dict[str, object] = {"items": [{"id": str(ITEM_ID)}], "results": [self.result_data()]}
        if case == "duplicate_items":
            data["items"] = [{"id": str(ITEM_ID)}, {"id": str(ITEM_ID)}]
        elif case == "duplicate_results":
            data["results"] = [self.result_data(), self.result_data()]
        else:
            data["items"] = [{"id": str(uuid4())}]
        serializer = UploadSubmissionSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)

    @parameterized.expand([("empty_results", "results"), ("too_many_results", "results"), ("too_many_items", "items")])
    def test_upload_batch_limits(self, case: str, field: str) -> None:
        data: dict[str, object] = {"results": [self.result_data()]}
        if case == "empty_results":
            data["results"] = []
        elif case == "too_many_results":
            data["results"] = [self.result_data()] * 1001
        else:
            data["items"] = [{"id": str(ITEM_ID)}] * 1001
        serializer = UploadSubmissionSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(field, serializer.errors)
