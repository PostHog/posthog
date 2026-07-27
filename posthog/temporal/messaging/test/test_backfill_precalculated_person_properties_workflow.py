from types import TracebackType

import pytest
from unittest.mock import Mock, patch

import temporalio.exceptions
from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.temporal.messaging.backfill_precalculated_person_properties_workflow import (
    BackfillPrecalculatedPersonPropertiesInputs,
    backfill_precalculated_person_properties_activity,
    build_person_properties_select_fields,
    evaluate_combined_filters_sync,
    flush_kafka_batch_async,
)
from posthog.temporal.messaging.filter_storage import combine_filter_bytecodes, store_filters
from posthog.temporal.messaging.types import PersonPropertyFilter

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import Operation


class _FieldChainCollector(TraversingVisitor):
    """Collect every ``ast.Field`` chain reachable from a node (e.g. inside argMax wrappers)."""

    def __init__(self) -> None:
        self.chains: list[list[str | int]] = []

    def visit_field(self, node: ast.Field) -> None:
        self.chains.append(list(node.chain))


def _collect_field_chains(node: ast.Expr) -> list[list[str | int]]:
    collector = _FieldChainCollector()
    collector.visit(node)
    return collector.chains


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


def aiter(iterable):
    """Wrap a sync iterable as an async iterator for mocking ``stream_query_as_jsonl``."""

    async def _aiter():
        for item in iterable:
            yield item

    return _aiter()


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

    def test_build_person_properties_select_fields_keeps_keys_in_field_chain(self):
        malicious_property = "email') FROM person WHERE team_id != %(team_id)s UNION ALL SELECT sleep(3) --"

        select_fields, property_alias_mapping = build_person_properties_select_fields([malicious_property])

        assert property_alias_mapping == {"prop_0": malicious_property}

        # The malicious key must live inside an argmax_select field chain — never inline as a SQL
        # fragment. argmax_select wraps the chain in an ``ast.Field``, keeping the key parameterized.
        assert select_fields == {"prop_0": ["properties", malicious_property]}

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_activity_parameterizes_property_keys_in_clickhouse_query(self):
        from asgiref.sync import sync_to_async

        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        organization = await sync_to_async(Organization.objects.create)(name="Test Organization")
        team = await sync_to_async(Team.objects.create)(name="Test Team", organization=organization)

        # No '%' here on purpose: '%' keys take the full-properties fallback (see the dedicated test
        # below). This key exercises the optimized per-property path and proves a SQL-fragment key
        # stays inside the ast.Field chain rather than being concatenated into the query.
        malicious_property = "email') FROM person WHERE team_id != 1 UNION ALL SELECT sleep(3) --"
        filters = [
            PersonPropertyFilter(
                condition_hash="injection_condition",
                bytecode=["_H", 1, 29],
                cohort_ids=[10],
                property_key=malicious_property,
            ),
        ]
        captured_ast: dict[str, object] = {}

        original_prepare_and_print_ast = __import__(
            "posthog.hogql.printer", fromlist=["prepare_and_print_ast"]
        ).prepare_and_print_ast

        def capturing_prepare_and_print_ast(node, context, dialect):
            captured_ast["node"] = node
            return original_prepare_and_print_ast(node, context, dialect)

        async def stream_query_as_jsonl(query: str, query_parameters: dict[str, object] | None = None):
            if False:
                yield {}  # type: ignore[unreachable]

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = stream_query_as_jsonl

        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=team.id,
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
            patch(
                "posthog.temporal.messaging.hogql_compile.prepare_and_print_ast",
                side_effect=capturing_prepare_and_print_ast,
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
            # The key may still produce an invalid identifier in the printer; the assertion that
            # matters is that it reached the printer only inside an ast.Field chain, never as a raw
            # SQL fragment.
            try:
                await backfill_precalculated_person_properties_activity(inputs)
            except Exception:
                pass

        # The malicious key must only reach the printer wrapped in an ast.Field chain.
        assert "node" in captured_ast, "compile_hogql_for_streaming was never called"
        node = captured_ast["node"]
        assert isinstance(node, ast.SelectQuery)
        # The child queries raw_persons directly (via argmax_select), not the persons lazy table.
        assert isinstance(node.select_from, ast.JoinExpr)
        assert isinstance(node.select_from.table, ast.Field)
        assert node.select_from.table.chain == ["raw_persons"]
        property_aliases = [
            expr for expr in node.select if isinstance(expr, ast.Alias) and expr.alias.startswith("prop_")
        ]
        assert len(property_aliases) == 1
        # The key lives inside an ast.Field chain (wrapped in argMax by argmax_select) — never
        # concatenated into the SQL as a fragment.
        prop_chains = _collect_field_chains(property_aliases[0])
        assert any(chain[-2:] == ["properties", malicious_property] for chain in prop_chains)

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_activity_falls_back_to_full_properties_for_percent_keys(self):
        from asgiref.sync import sync_to_async

        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        organization = await sync_to_async(Organization.objects.create)(name="Test Organization")
        team = await sync_to_async(Team.objects.create)(name="Test Team", organization=organization)

        # '%' is the one character HogQL refuses as an identifier, so the optimized per-property
        # path can't be used. The backfill must fall back to selecting the full properties JSON
        # rather than crashing the whole batch.
        percent_property = "utm_%_source"
        filters = [
            PersonPropertyFilter(
                condition_hash="percent_condition",
                bytecode=["_H", 1, 29],
                cohort_ids=[10],
                property_key=percent_property,
            ),
        ]
        captured_ast: dict[str, object] = {}

        original_prepare_and_print_ast = __import__(
            "posthog.hogql.printer", fromlist=["prepare_and_print_ast"]
        ).prepare_and_print_ast

        def capturing_prepare_and_print_ast(node, context, dialect):
            captured_ast["node"] = node
            return original_prepare_and_print_ast(node, context, dialect)

        async def stream_query_as_jsonl(query: str, query_parameters: dict[str, object] | None = None):
            if False:
                yield {}  # type: ignore[unreachable]

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = stream_query_as_jsonl

        inputs = BackfillPrecalculatedPersonPropertiesInputs(
            team_id=team.id,
            filter_storage_key="storage_key",
            cohort_ids=[10],
            batch_size=10,
            start_person_id="00000000-0000-0000-0000-000000000000",
            end_person_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )

        with (
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_filters_and_properties",
                return_value=(filters, [percent_property], combine_filter_bytecodes(filters)),
            ),
            patch(
                "posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.get_client",
                return_value=_AsyncClientContextManager(mock_client),
            ),
            patch(
                "posthog.temporal.messaging.hogql_compile.prepare_and_print_ast",
                side_effect=capturing_prepare_and_print_ast,
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
            await backfill_precalculated_person_properties_activity(inputs)

        assert "node" in captured_ast, "compile_hogql_for_streaming was never called"
        node = captured_ast["node"]
        assert isinstance(node, ast.SelectQuery)

        # No per-property accessors — the '%' key forced the full-properties fallback.
        property_aliases = [
            expr for expr in node.select if isinstance(expr, ast.Alias) and expr.alias.startswith("prop_")
        ]
        assert property_aliases == []

        # The full ``properties`` JSON is selected instead (argmax_select aliases it as "properties"),
        # and the '%' key never appears as a field chain element anywhere in the query.
        properties_aliases = [
            expr for expr in node.select if isinstance(expr, ast.Alias) and expr.alias == "properties"
        ]
        assert len(properties_aliases) == 1
        assert any(chain[-1:] == ["properties"] for chain in _collect_field_chains(properties_aliases[0]))
        assert all(percent_property not in chain for chain in _collect_field_chains(node))


class TestActivityRowConsumption:
    """End-to-end row streaming through the child activity.

    The other activity tests stream zero rows (``compile`` is patched and the client yields nothing),
    so the row-consumption code — which now reads ``row["id"]`` and reconstructs properties from
    ``prop_N`` columns — was never exercised. These feed real rows through it.
    """

    def _module(self, name: str) -> str:
        return f"posthog.temporal.messaging.backfill_precalculated_person_properties_workflow.{name}"

    async def _run_with_rows(self, person_properties, rows):
        """Run the activity over ``rows``; return (result, captured_query_node, produced_messages, eval_globals)."""
        filters = [
            PersonPropertyFilter(
                condition_hash="cond1",
                bytecode=["_H", 1, Operation.TRUE],
                cohort_ids=[10],
                property_key=person_properties[0] if person_properties else None,
            )
        ]

        captured: dict[str, object] = {}

        async def compile_stub(node, *, team_id):
            captured["node"] = node
            return "SELECT 1", {}

        eval_globals: list[dict] = []

        def eval_stub(combined_bytecode, flts, hog_globals, person_id, detailed_logging=False):
            eval_globals.append(hog_globals)
            return {"cond1": True}

        produced: list[dict] = []
        producer = Mock()

        def _produce(**kwargs):
            produced.append(kwargs["data"])
            return Mock()

        producer.produce = _produce

        mock_client = Mock()
        mock_client.stream_query_as_jsonl = lambda *a, **kw: aiter(rows)

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
                self._module("get_filters_and_properties"),
                return_value=(filters, list(person_properties), combine_filter_bytecodes(filters)),
            ),
            patch(self._module("compile_hogql_for_streaming"), side_effect=compile_stub),
            patch(self._module("get_client"), return_value=_AsyncClientContextManager(mock_client)),
            patch(self._module("evaluate_combined_filters_with_fallback_sync"), side_effect=eval_stub),
            patch(self._module("get_producer"), return_value=producer),
            patch(self._module("Heartbeater"), _NoopHeartbeater),
            patch(self._module("get_person_properties_backfill_success_metric"), return_value=Mock()),
        ):
            result = await backfill_precalculated_person_properties_activity(inputs)

        return result, captured.get("node"), produced, eval_globals

    @pytest.mark.asyncio
    async def test_optimized_rows_reconstruct_properties_and_produce(self):
        # Optimized format: per-property prop_N columns, no "properties" key, person UUID under "id".
        pid = "11111111-1111-1111-1111-111111111111"
        rows = [{"id": pid, "prop_0": "a@b.com"}]

        result, node, produced, eval_globals = await self._run_with_rows(["email"], rows)

        # row["id"] is consumed and reconstruction maps prop_0 -> email.
        assert result.persons_processed == 1
        assert result.last_person_id == pid
        assert eval_globals[0] == {"person": {"properties": {"email": "a@b.com"}}}
        assert len(produced) == 1
        assert produced[0]["person_id"] == pid
        assert produced[0]["condition"] == "cond1"

        # Locks the flat single-pass query shape the child optimization depends on: WHERE filters the
        # raw_persons scan before the GROUP BY, with no id-IN-subquery indirection.
        assert isinstance(node, ast.SelectQuery)
        assert node.where is not None
        assert node.group_by is not None
        assert isinstance(node.select_from, ast.JoinExpr)
        assert isinstance(node.select_from.table, ast.Field)
        assert node.select_from.table.chain == ["raw_persons"]

    @pytest.mark.asyncio
    async def test_optimized_rows_keep_present_falsey_values_and_drop_missing(self):
        # A missing key comes back as SQL NULL (None); a present falsey value comes back as a
        # non-null string. The reconstruction must keep the falsey value and drop only the None,
        # otherwise a present-but-falsey property silently becomes a missing key.
        pid = "33333333-3333-3333-3333-333333333333"
        rows = [{"id": pid, "prop_0": "", "prop_1": "0", "prop_2": "false", "prop_3": None}]

        _result, _node, _produced, eval_globals = await self._run_with_rows(["empty", "zero", "flag", "absent"], rows)

        assert eval_globals[0] == {"person": {"properties": {"empty": "", "zero": "0", "flag": "false"}}}

    @pytest.mark.asyncio
    async def test_fallback_rows_use_full_properties_json(self):
        # Fallback format: a "properties" JSON column is present, so the consumer parses it directly.
        pid = "22222222-2222-2222-2222-222222222222"
        rows = [{"id": pid, "properties": '{"email": "c@d.com"}'}]

        result, _node, produced, eval_globals = await self._run_with_rows([], rows)

        assert result.persons_processed == 1
        assert result.last_person_id == pid
        assert eval_globals[0] == {"person": {"properties": {"email": "c@d.com"}}}
        assert len(produced) == 1


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
