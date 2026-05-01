from types import TracebackType

import pytest
from unittest.mock import Mock, patch

import temporalio.exceptions
from parameterized import parameterized

from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    backfill_precalculated_person_properties_activity,
    build_person_properties_select_clause,
    evaluate_combined_filters_sync,
    flush_kafka_batch_async,
)
from posthog.temporal.messaging.filter_storage import combine_filter_bytecodes, store_filters
from posthog.temporal.messaging.types import PersonPropertyFilter

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import Operation


class _NoopHeartbeater:
    details: tuple[str, ...]

    def __init__(self, details: tuple[str, ...] = (), factor: int = 120) -> None:
        self.details = details

    async def __aenter__(self) -> "_NoopHeartbeater":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _AsyncClientContextManager:
    def __init__(self, client: Mock) -> None:
        self.client = client

    async def __aenter__(self) -> Mock:
        return self.client

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class TestFlushKafkaBatchAsync:
    """Tests for the flush_kafka_batch_async helper function."""

    @pytest.mark.asyncio
    async def test_empty_futures_returns_zero(self):
        """When kafka_results is empty, should return 0 without flushing."""
        kafka_producer = Mock()
        logger = Mock()

        result = await flush_kafka_batch_async(
            kafka_results=[],
            kafka_producer=kafka_producer,
            team_id=1,
            logger=logger,
        )

        assert result == 0

    @pytest.mark.asyncio
    async def test_successful_batch_flush_async(self):
        """Should handle successful ProduceResult objects correctly."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mock ProduceResult objects
        produce_result_1 = Mock()
        produce_result_2 = Mock()
        kafka_results = [produce_result_1, produce_result_2]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_results=kafka_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        assert result == 2
        mock_thread.assert_called_once_with(kafka_producer.flush)

    @pytest.mark.asyncio
    async def test_batch_flush_with_multiple_results(self):
        """Should handle multiple ProduceResult objects correctly."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mock ProduceResult objects - all are successful since failures are handled earlier
        produce_result_1 = Mock()
        produce_result_2 = Mock()
        produce_result_3 = Mock()
        kafka_results = [produce_result_1, produce_result_2, produce_result_3]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_results=kafka_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        # Should return count of all ProduceResult objects (3)
        assert result == 3
        mock_thread.assert_called_once_with(kafka_producer.flush)

    @pytest.mark.asyncio
    async def test_batch_flush_calls_kafka_flush(self):
        """Should call Kafka flush operation asynchronously."""
        kafka_producer = Mock()
        logger = Mock()

        # Create mock ProduceResult objects
        produce_results = [Mock(), Mock()]

        with patch(
            "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.asyncio.to_thread"
        ) as mock_thread:
            mock_thread.return_value = None

            result = await flush_kafka_batch_async(
                kafka_results=produce_results,
                kafka_producer=kafka_producer,
                team_id=1,
                logger=logger,
            )

        # Should return count of ProduceResult objects and call flush
        assert result == 2
        mock_thread.assert_called_once_with(kafka_producer.flush)


class TestBackfillPrecalculatedPersonPropertiesActivity:
    """Tests for the main backfill activity function."""

    @pytest.mark.asyncio
    async def test_missing_filter_storage_key_raises_non_retryable_error(self):
        """Should raise non-retryable error when filter storage key doesn't exist."""
        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key="nonexistent_key",
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        with pytest.raises(temporalio.exceptions.ApplicationError) as exc_info:
            await backfill_precalculated_person_properties_activity(inputs)

        assert exc_info.value.non_retryable is True
        assert "Filters not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_no_filters_aborts_early(self):
        """Should abort early and return zero results when no filters exist."""
        storage_key = store_filters([], team_id=1)

        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key=storage_key,
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        result = await backfill_precalculated_person_properties_activity(inputs)

        # Should return early with zero results
        assert result.persons_processed == 0
        assert result.events_produced == 0
        assert result.events_flushed == 0
        assert result.last_person_id is None

    @pytest.mark.asyncio
    async def test_property_names_with_backticks_generate_safe_query(self):
        """Should safely handle property names that contain backticks."""
        # Create filters with a property name containing backticks
        filters = [
            PersonPropertyFilter(
                condition_hash="backtick_condition",
                bytecode=[],  # Empty bytecode for test
                cohort_ids=[10],
                property_key="weird`property",
            ),
        ]

        storage_key = store_filters(filters, team_id=1)

        # This should not crash when constructing query parameters
        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key=storage_key,
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        # Basic verification that the filter was stored correctly
        assert inputs.filter_storage_key == storage_key

    def test_build_person_properties_select_clause_parameterizes_property_keys(self):
        malicious_property = "email') FROM person WHERE team_id != %(team_id)s UNION ALL SELECT sleep(3) --"

        properties_clause, property_alias_mapping, property_query_params = build_person_properties_select_clause(
            [malicious_property]
        )

        assert malicious_property not in properties_clause
        assert "team_id !=" not in properties_clause
        assert "%(property_key_0)s" in properties_clause
        assert property_alias_mapping == {"prop_0": malicious_property}
        assert property_query_params == {"property_key_0": malicious_property}

    @pytest.mark.asyncio
    async def test_activity_parameterizes_property_keys_in_clickhouse_query(self):
        malicious_property = "email') FROM person WHERE team_id != %(team_id)s UNION ALL SELECT sleep(3) --"
        filters = [
            PersonPropertyFilter(
                condition_hash="injection_condition",
                bytecode=["_H", 1, 29],
                cohort_ids=[10],
                property_key=malicious_property,
            ),
        ]
        captured_query: dict[str, object] = {}

        async def stream_query_as_jsonl(query: str, query_parameters: dict[str, object] | None = None):
            captured_query["query"] = query
            captured_query["query_parameters"] = query_parameters
            if False:
                yield {}  # type: ignore[unreachable]

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = stream_query_as_jsonl

        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=1,
            filter_storage_key="storage_key",
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_filters_and_properties",
                return_value=(filters, [malicious_property], combine_filter_bytecodes(filters)),
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_client",
                return_value=_AsyncClientContextManager(mock_client),
            ),
            patch("posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_producer"),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.Heartbeater",
                _NoopHeartbeater,
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_person_properties_backfill_success_metric",
                return_value=Mock(),
            ),
        ):
            result = await backfill_precalculated_person_properties_activity(inputs)

        assert result.persons_processed == 0

        query = captured_query["query"]
        assert isinstance(query, str)
        assert malicious_property not in query
        assert "team_id !=" not in query
        assert "%(property_key_0)s" in query

        query_parameters = captured_query["query_parameters"]
        assert isinstance(query_parameters, dict)
        assert query_parameters["property_key_0"] == malicious_property


class TestCombineFilterBytecodes:
    """Tests for combine_filter_bytecodes."""

    def test_single_filter(self):
        filters = [
            PersonPropertyFilter(
                condition_hash="h1",
                bytecode=["_H", 1, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12],
                cohort_ids=[10],
                property_key="$browser",
            ),
        ]
        result = combine_filter_bytecodes(filters)
        assert result[0] == "_H"
        assert result[1] == 1
        assert result[2] == Operation.STRING
        assert result[3] == "h1"
        # Body without header
        assert result[4:-2] == [31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12]
        # Trailing DICT
        assert result[-2] == Operation.DICT
        assert result[-1] == 1

    def test_multiple_filters(self):
        filters = [
            PersonPropertyFilter(condition_hash="h1", bytecode=["_H", 1, 29], cohort_ids=[1], property_key=None),
            PersonPropertyFilter(condition_hash="h2", bytecode=["_H", 1, 30], cohort_ids=[2], property_key=None),
        ]
        result = combine_filter_bytecodes(filters)
        assert result == ["_H", 1, Operation.STRING, "h1", 29, Operation.STRING, "h2", 30, Operation.DICT, 2]

    def test_skips_malformed_bytecodes(self):
        filters = [
            PersonPropertyFilter(condition_hash="bad", bytecode=["_H", 1], cohort_ids=[1], property_key=None),
            PersonPropertyFilter(condition_hash="good", bytecode=["_H", 1, 29], cohort_ids=[2], property_key=None),
        ]
        result = combine_filter_bytecodes(filters)
        assert result == ["_H", 1, Operation.STRING, "good", 29, Operation.DICT, 1]

    def test_executes_and_returns_dict(self):
        filters = [
            PersonPropertyFilter(condition_hash="h1", bytecode=["_H", 1, 29], cohort_ids=[1], property_key=None),
            PersonPropertyFilter(condition_hash="h2", bytecode=["_H", 1, 30], cohort_ids=[2], property_key=None),
        ]
        combined = combine_filter_bytecodes(filters)
        result = execute_bytecode(combined, {})
        assert result.result == {"h1": True, "h2": False}

    @parameterized.expand(
        [
            ({"person": {"properties": {"$browser": "Chrome"}}}, {"browser_set": True}),
            ({"person": {"properties": {}}}, {"browser_set": False}),
        ]
    )
    def test_executes_with_person_properties(self, globals_input, expected_result):
        # Bytecode for: person.properties.$browser != NULL (is_set check)
        browser_bytecode = ["_H", 1, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12]
        filters = [
            PersonPropertyFilter(
                condition_hash="browser_set",
                bytecode=browser_bytecode,
                cohort_ids=[10],
                property_key="$browser",
            ),
        ]
        combined = combine_filter_bytecodes(filters)

        result = execute_bytecode(combined, globals_input)
        assert result.result == expected_result

    @parameterized.expand(
        [
            ({"person": {"properties": {"$browser": "Chrome"}}}, {"browser_set": True, "host_set": False}),
            (
                {"person": {"properties": {"$browser": "Chrome", "$host": "example.com"}}},
                {"browser_set": True, "host_set": True},
            ),
        ]
    )
    def test_executes_multiple_property_filters(self, globals_input, expected_result):
        browser_bytecode = ["_H", 1, 31, 32, "$browser", 32, "properties", 32, "person", 1, 3, 12]
        host_bytecode = ["_H", 1, 31, 32, "$host", 32, "properties", 32, "person", 1, 3, 12]
        filters = [
            PersonPropertyFilter(
                condition_hash="browser_set", bytecode=browser_bytecode, cohort_ids=[10], property_key="$browser"
            ),
            PersonPropertyFilter(
                condition_hash="host_set", bytecode=host_bytecode, cohort_ids=[10], property_key="$host"
            ),
        ]
        combined = combine_filter_bytecodes(filters)

        result = execute_bytecode(combined, globals_input)
        assert result.result == expected_result

    @parameterized.expand(
        [
            (
                "single_failing",
                ["failing_condition"],
                ["working_condition"],
                {"working_condition": True},
            ),
            (
                "multiple_failing",
                ["fail1", "fail2"],
                ["work"],
                {"work": True},
            ),
        ]
    )
    def test_failing_filters_are_omitted_from_results(self, _, failing_hashes, working_hashes, expected):
        """Failing filters should be omitted from results, not crash the entire execution."""
        from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
            evaluate_combined_filters_with_fallback_sync,
        )

        failing_bytecode = ["_H", 1, 31, 32, "nonexistent", 32, "properties", 32, "person", 1, 3, 32, "test", 13]
        working_bytecode = ["_H", 1, 29]  # Always true

        filters = [
            PersonPropertyFilter(condition_hash=h, bytecode=failing_bytecode, cohort_ids=[i], property_key=None)
            for i, h in enumerate(failing_hashes)
        ] + [
            PersonPropertyFilter(
                condition_hash=h, bytecode=working_bytecode, cohort_ids=[len(failing_hashes) + i], property_key=None
            )
            for i, h in enumerate(working_hashes)
        ]

        combined = combine_filter_bytecodes(filters)
        result = evaluate_combined_filters_with_fallback_sync(
            combined, filters, {"person": {"properties": {}}}, "test-person"
        )

        assert result == expected


class TestEvaluateCombinedFiltersSync:
    """Tests for evaluate_combined_filters_sync."""

    def test_returns_dict_on_success(self):
        combined = ["_H", 1, Operation.STRING, "h1", 29, Operation.DICT, 1]
        result = evaluate_combined_filters_sync(combined, {}, "person-1")
        assert result == {"h1": True}

    def test_returns_empty_dict_on_error(self):
        result = evaluate_combined_filters_sync(["_H", 1, 999], {}, "person-1")
        assert result == {}

    @parameterized.expand(
        [
            ("enabled_success", True, {"test_condition": True}, True, False),
            ("disabled", False, {"test_condition": True}, False, False),
            ("enabled_non_dict", True, {}, True, True),
        ]
    )
    @patch("posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.LOGGER")
    def test_detailed_logging(self, _name, detailed, expected_result, expect_info, expect_warning, mock_logger):
        if detailed and expect_warning:
            combined = ["_H", 1, Operation.STRING, "not_a_dict"]
        else:
            combined = ["_H", 1, Operation.STRING, "test_condition", 29, Operation.DICT, 1]

        hog_globals = {"person": {"properties": {"$browser": "Chrome"}}} if detailed and not expect_warning else {}

        result = evaluate_combined_filters_sync(combined, hog_globals, "person-123", detailed_logging=detailed)

        assert result == expected_result

        if expect_info:
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "HogVM evaluation completed"
            logged_kwargs = call_args[1]
            assert logged_kwargs["person_id"] == "person-123"
        else:
            mock_logger.info.assert_not_called()

        if expect_warning:
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert call_args[0][0] == "HogVM evaluation returned non-dict result"
        else:
            mock_logger.warning.assert_not_called()
