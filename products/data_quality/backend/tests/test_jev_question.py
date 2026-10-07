import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, patch

from django.test import override_settings

import httpx
import pyarrow as pa
import fakeredis
from asgiref.sync import async_to_sync
from pydantic import ValidationError
from redis.exceptions import ConnectionError

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.transforms.prompt_jev import PromptJevColumn, PromptJevTable

from posthog.models.team import Team
from posthog.models.user import User

from products.data_quality.backend.facade.enums import CheckRunStatus, SubjectType
from products.data_quality.backend.logic.compiler import print_check_query
from products.data_quality.backend.logic.contracts import SubjectRef
from products.data_quality.backend.logic.jev_cache import (
    EVALUATOR_VERSION,
    DecisionCacheUnavailable,
    DecisionRequest,
    JevDecisionCache,
)
from products.data_quality.backend.logic.jev_evaluator import QuestionGatewayEvaluator
from products.data_quality.backend.logic.jev_manifest import (
    QuestionManifest,
    QuestionManifestStore,
    QuestionResult,
    evaluate_question_manifest,
    freeze_question_inputs,
    strict_arrow_batches,
    warehouse_question_inputs,
)
from products.data_quality.backend.logic.jev_question import (
    QuestionChunkEvaluator,
    QuestionChunkResult,
    QuestionConfig,
    WeightedInput,
    question_input_query,
)


def request(text: str = "input") -> DecisionRequest:
    return DecisionRequest(
        input=text,
        question_schema=QuestionConfig(question="Is this valid?").question_schema(),
        model_id="example-model",
        model_revision="immutable-revision-1",
    )


def evaluator(
    cache: JevDecisionCache, evaluate: Callable[[list[str]], list[float]], **config: float
) -> QuestionChunkEvaluator:
    return QuestionChunkEvaluator(
        cache=cache,
        config=QuestionConfig(question="Is this valid?", **config),
        model_id="example-model",
        model_revision="immutable-revision-1",
        evaluate=evaluate,
        wait_seconds=10_000,
    )


@pytest.mark.parametrize(
    "changed",
    [
        replace(request(), input="input "),
        replace(request(), question_schema='{"type":"noul","instructions":"Different?"}'),
        replace(request(), model_revision="immutable-revision-2"),
        replace(request(), model_id="other-model"),
        replace(request(), evaluator_version=2),
        replace(request(), input='[["field", "String", "1"]]'),
        replace(request(), input='[["field", "Int64", 1]]'),
        replace(request(), input='[["other", "String", "1"]]'),
        replace(request(), input='[["field", "Nullable(String)", null]]'),
    ],
)
def test_cache_identity(changed: DecisionRequest) -> None:
    original = request()
    assert changed.key(1) != original.key(1)
    assert original.key(2) != original.key(1)
    assert "input" not in original.key(1)


def test_expired_owner_cannot_publish_or_release_winning_lease() -> None:
    client = fakeredis.FakeRedis()
    cache = JevDecisionCache(client, team_id=1)
    decision = request()
    key = decision.key(1)
    loser = cache.acquire([decision])[key]
    client.delete(key + ":lease")
    winner = cache.acquire([decision])[key]
    assert cache.publish([(loser, decision, 0.1)]) == set()
    cache.release([loser])
    winning_token = client.get(key + ":lease")
    assert winning_token is not None
    assert winning_token.decode() == winner.token
    assert cache.publish([(winner, decision, 0.9)]) == {key}
    assert cache.read([decision]) == {key: 0.9}
    stored = client.get(key)
    assert stored is not None
    assert set(json.loads(stored)) == {"probability", "model_revision", "evaluator_version", "evaluated_at"}


def test_renewal_is_bounded_and_reads_do_not_extend_ttl() -> None:
    client = fakeredis.FakeRedis()
    cache = JevDecisionCache(client, team_id=1, max_renewals=1)
    decision = request()
    key = decision.key(1)
    lease = cache.acquire([decision])[key]
    renewed = cache.renew(lease)
    assert renewed is not None
    assert cache.renew(renewed) is None
    cache.publish([(renewed, decision, 0.9)])
    client.expire(key, 100)
    cache.read([decision])
    assert 0 < client.ttl(key) <= 100
    client.delete(key)
    assert cache.read([decision]) == {}


@pytest.mark.parametrize("unavailable", [False, True])
def test_evaluation_lease_renewal_preserves_ownership_or_errors(unavailable: bool) -> None:
    client = fakeredis.FakeRedis()
    cache = JevDecisionCache(client, team_id=1)
    decision = request()
    key = decision.key(1)
    lease = cache.acquire([decision])[key]
    client.expire(key + ":lease", 1)
    with patch("products.data_quality.backend.logic.jev_cache.Event") as stopped:
        stopped.return_value.wait.side_effect = [False, True]
        if unavailable:
            with patch.object(client, "pipeline", side_effect=ConnectionError()):
                with pytest.raises(DecisionCacheUnavailable, match="unavailable"):
                    with cache.maintain([lease]):
                        pass
        else:
            with cache.maintain([lease]):
                pass
            assert client.ttl(key + ":lease") > 1
            assert cache.publish([(lease, decision, 0.9)]) == {key}


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_probability_never_enters_cache(probability: float) -> None:
    client = fakeredis.FakeRedis()
    cache = JevDecisionCache(client, team_id=1)
    decision = request()
    lease = cache.acquire([decision])[decision.key(1)]
    with pytest.raises(ValueError):
        cache.publish([(lease, decision, probability)])
    assert cache.read([decision]) == {}


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"probability":0.5}',
        '{"probability":NaN,"model_revision":"immutable-revision-1","evaluator_version":1,"evaluated_at":"2026-01-01T00:00:00Z"}',
        '{"probability":0.5,"model_revision":"wrong","evaluator_version":1,"evaluated_at":"2026-01-01T00:00:00Z"}',
        '{"probability":0.5,"model_revision":"immutable-revision-1","evaluator_version":1,"evaluated_at":"2026-01-01T00:00:00"}',
    ],
)
def test_malformed_cache_entry_is_replaced(content: str) -> None:
    client = fakeredis.FakeRedis()
    cache = JevDecisionCache(client, team_id=1)
    client.set(request().key(1), content)
    result = evaluator(cache, lambda inputs: [0.9] * len(inputs)).run([WeightedInput(text="input", row_count=1)])
    assert result.new_decision_count == 1
    assert cache.read([request()]) == {request().key(1): 0.9}


def test_redis_outage_does_not_fall_back_to_inference() -> None:
    client = fakeredis.FakeRedis()
    calls: list[str] = []

    def evaluate(inputs: list[str]) -> list[float]:
        calls.extend(inputs)
        return [0.9] * len(inputs)

    with patch.object(client, "mget", side_effect=ConnectionError()):
        with pytest.raises(DecisionCacheUnavailable, match="unavailable"):
            evaluator(JevDecisionCache(client, team_id=1), evaluate).run([WeightedInput(text="input", row_count=1)])
    assert calls == []


def test_threshold_change_reuses_decisions_and_nulls_fail_without_inference() -> None:
    client = fakeredis.FakeRedis()
    cache = JevDecisionCache(client, team_id=1)
    calls: list[str] = []

    def evaluate(inputs: list[str]) -> list[float]:
        calls.extend(inputs)
        return [0.8] * len(inputs)

    inputs = [
        WeightedInput(text="a", row_count=3),
        WeightedInput(text="a", row_count=2),
        WeightedInput(text=None, row_count=4),
    ]
    cold = evaluator(cache, evaluate).run(inputs)
    assert (cold.examined_row_count, cold.failed_row_count, cold.new_decision_count) == (9, 4, 1)
    warm = evaluator(cache, evaluate, min_probability=0.9).run(inputs)
    assert (warm.examined_row_count, warm.failed_row_count, warm.reused_decision_count, warm.new_decision_count) == (
        9,
        9,
        1,
        0,
    )
    assert calls == ["a"]


@pytest.mark.parametrize(
    "config,column_name",
    [
        ({"question": "   "}, "description"),
        ({"question": "Valid?", "min_probability": float("nan")}, "description"),
        ({"question": "Valid?", "max_failure_rate": 1.1}, "description"),
        ({"question": "Valid?", "input_mode": "row", "columns": []}, ""),
        ({"question": "Valid?", "input_mode": "row", "columns": ["a", "a"]}, ""),
        ({"question": "Valid?", "input_mode": "row", "columns": ["a"]}, "description"),
        ({"question": "Valid?", "columns": ["a"]}, "description"),
        ({"question": "Valid?"}, ""),
    ],
)
def test_modes_and_thresholds_are_validated(config: dict[str, object], column_name: str) -> None:
    with pytest.raises((ValueError, ValidationError)):
        QuestionConfig(**config).input_columns(column_name)


def test_exhaustive_question_projection_has_typed_fields_and_no_limit() -> None:
    subject = SubjectRef(SubjectType.TABLE, "example-table", "orders", "orders", exists=True)
    config = QuestionConfig(input_mode="row", question="Valid?", columns=["description", "amount"])
    printed = print_check_query(question_input_query(subject, config, ""))
    assert "LIMIT" not in printed
    assert "GROUP BY" in printed
    assert "toTypeName(amount)" in printed
    assert "toTypeName(description)" in printed
    assert printed.index("'amount'") < printed.index("'description'")
    context = HogQLContext(
        team_id=999,
        team=Team(id=999, project_id=999),
        database=Database(include_posthog_tables=False),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
        use_new_events_schema=False,
    )
    PromptJevTable(
        name="orders",
        columns=[
            PromptJevColumn(name="amount", clickhouse_type="Int64"),
            PromptJevColumn(name="description", clickhouse_type="String"),
        ],
        rows=[],
    ).register(context)
    sql, prepared = prepare_and_print_ast(
        question_input_query(subject, config, ""), context=context, dialect="clickhouse"
    )
    assert prepared is not None
    assert "LIMIT" not in sql
    assert sql.count("toJSONString(tuple(") == 2
    assert "arrayStringConcat" in sql


def _arrow_stream(*texts: str) -> bytes:
    fields: list[pa.Field] = [pa.field("input", pa.string()), pa.field("row_count", pa.uint64())]
    schema = pa.schema(fields)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        for text in texts:
            writer.write_batch(pa.record_batch([[text], [1]], schema=schema))
    return sink.getvalue().to_pybytes()


ONE_BATCH_WITHOUT_END = _arrow_stream("first")[:-8]


@pytest.mark.parametrize(
    "body,error",
    [
        (_arrow_stream("first", "second"), None),
        (ONE_BATCH_WITHOUT_END, "before its end marker"),
        (_arrow_stream("first", "second")[: len(ONE_BATCH_WITHOUT_END) + 24], "before its end marker"),
        (_arrow_stream("first", "second") + b"Code: 241. DB::Exception: example", "after its end marker"),
    ],
    ids=["complete", "cut_at_batch_boundary", "cut_inside_batch", "trailing_error"],
)
def test_arrow_input_stream_must_end_at_its_end_marker(body: bytes, error: str | None) -> None:
    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(body), 7):
            yield body[start : start + 7]

    async def collect() -> list[str]:
        return [row["input"] async for batch in strict_arrow_batches(chunks()) for row in batch.to_pylist()]

    if error is None:
        assert async_to_sync(collect)() == ["first", "second"]
    else:
        with pytest.raises(ValueError, match=error):
            async_to_sync(collect)()


@pytest.mark.usefixtures("clickhouse_database")
def test_row_inputs_keep_null_and_non_finite_numbers_distinct() -> None:
    subject = SubjectRef(SubjectType.TABLE, "example-table", "orders", "orders", exists=True)
    config = QuestionConfig(input_mode="row", question="Valid?", columns=["amount"])
    team = Team(id=999, project_id=999)
    context = HogQLContext(
        team_id=999,
        team=team,
        database=Database(include_posthog_tables=False),
        enable_select_queries=True,
        limit_top_select=False,
        restricted_properties=set(),
        use_new_events_schema=False,
        output_format="ArrowStream",
    )
    PromptJevTable(
        name="orders",
        columns=[PromptJevColumn(name="amount", clickhouse_type="Nullable(Float64)")],
        rows=[[None], [float("nan")], [float("inf")], [float("-inf")]],
    ).register(context)
    sql, _ = prepare_and_print_ast(question_input_query(subject, config, ""), context=context, dialect="clickhouse")

    async def collect() -> list[WeightedInput]:
        return [
            item
            async for item in warehouse_question_inputs(
                team=team, user=cast(User, SimpleNamespace()), subject=subject, config=config, column_name=""
            )
        ]

    with patch(
        "products.data_quality.backend.logic.jev_manifest.prepare_warehouse_question_inputs",
        return_value=(sql, context),
    ):
        inputs = async_to_sync(collect)()
    assert sorted((item.text or "", item.row_count) for item in inputs) == [
        ('[["amount","Nullable(Float64)","-inf"]]', 1),
        ('[["amount","Nullable(Float64)","inf"]]', 1),
        ('[["amount","Nullable(Float64)","nan"]]', 1),
        ('[["amount","Nullable(Float64)",null]]', 1),
    ]


def test_full_manifest_coverage_cold_warm_and_retry() -> None:
    objects: dict[str, str] = {}
    checkpoints: dict[int, QuestionChunkResult] = {}
    store = QuestionManifestStore()
    cache = JevDecisionCache(fakeredis.FakeRedis(), team_id=1)
    calls: list[str] = []

    async def source() -> AsyncIterator[WeightedInput]:
        for index in range(500):
            yield WeightedInput(text=str(index), row_count=40)

    def evaluate(inputs: list[str]) -> list[float]:
        calls.extend(inputs)
        return [0.1 if text == "0" else 0.8 for text in inputs]

    with (
        patch(
            "posthog.storage.object_storage.write", side_effect=lambda key, content: objects.__setitem__(key, content)
        ),
        patch("posthog.storage.object_storage.read", side_effect=lambda key: objects.get(key)),
    ):
        manifest = async_to_sync(freeze_question_inputs)(
            inputs=source(),
            store=store,
            team_id=1,
            run_id="example-run",
            subject_uuid="example-table",
            model_id="example-model",
            model_revision="immutable-revision-1",
            config=QuestionConfig(question="Is this valid?"),
            column_name="description",
        )
        assert manifest.chunk_count == 4

        def save(index: int, result: QuestionChunkResult) -> QuestionChunkResult:
            if index == 2:
                raise RuntimeError("checkpoint unavailable")
            return checkpoints.setdefault(index, result)

        def run(save_checkpoint: Callable[[int, QuestionChunkResult], QuestionChunkResult]) -> QuestionResult:
            return evaluate_question_manifest(
                manifest=manifest,
                store=store,
                evaluator=evaluator(cache, evaluate),
                authorize=lambda: None,
                load_checkpoint=checkpoints.get,
                save_checkpoint=save_checkpoint,
            )

        with pytest.raises(RuntimeError, match="checkpoint unavailable"):
            run(save)
        assert len(checkpoints) == 2
        cold = run(lambda index, result: checkpoints.setdefault(index, result))
        assert cold.status == CheckRunStatus.FAILED
        assert (cold.examined_row_count, cold.failed_row_count, cold.unique_input_count) == (20_000, 40, 500)
        assert cold.coverage_complete
        assert len(calls) == 500
        checkpoints.clear()
        warm = run(lambda index, result: checkpoints.setdefault(index, result))
        assert (warm.examined_row_count, warm.reused_decision_count, warm.new_decision_count) == (20_000, 500, 0)
        assert len(calls) == 500


@pytest.mark.parametrize(
    "texts,max_inputs,message",
    [(["a" * 8193], 200, "8 KiB"), ([str(index) for index in range(200)], 130, "frozen inputs")],
)
def test_oversized_freeze_fails_closed_and_publishes_nothing(texts: list[str], max_inputs: int, message: str) -> None:
    objects: dict[str, str] = {}

    async def source() -> AsyncIterator[WeightedInput]:
        for text in texts:
            yield WeightedInput(text=text, row_count=1)

    with (
        patch(
            "posthog.storage.object_storage.write", side_effect=lambda key, content: objects.__setitem__(key, content)
        ),
        patch("posthog.storage.object_storage.delete", side_effect=lambda key: objects.pop(key, None)),
        pytest.raises(ValueError, match=message),
    ):
        async_to_sync(freeze_question_inputs)(
            inputs=source(),
            store=QuestionManifestStore(),
            team_id=1,
            run_id="example-run",
            subject_uuid="example-table",
            model_id="example-model",
            model_revision="immutable-revision-1",
            config=QuestionConfig(question="Is this valid?"),
            column_name="description",
            max_inputs=max_inputs,
        )
    assert objects == {}


def test_manifest_checkpoint_coverage_mismatch_and_permission_revocation_fail_closed() -> None:
    store = QuestionManifestStore()
    cache = JevDecisionCache(fakeredis.FakeRedis(), team_id=1)

    async def source() -> AsyncIterator[WeightedInput]:
        yield WeightedInput(text="input", row_count=10)

    with patch("posthog.storage.object_storage.write"):
        manifest = async_to_sync(freeze_question_inputs)(
            inputs=source(),
            store=store,
            team_id=1,
            run_id="example-run",
            subject_uuid="example-table",
            model_id="example-model",
            model_revision="immutable-revision-1",
            config=QuestionConfig(question="Is this valid?"),
            column_name="description",
        )

    def run(
        frozen: QuestionManifest, authorize: Callable[[], None], checkpoint: QuestionChunkResult | None = None
    ) -> QuestionResult:
        return evaluate_question_manifest(
            manifest=frozen,
            store=store,
            evaluator=evaluator(cache, lambda inputs: [0.9]),
            authorize=authorize,
            load_checkpoint=lambda index: checkpoint,
            save_checkpoint=lambda index, result: result,
        )

    def deny() -> None:
        raise PermissionError()

    with pytest.raises(PermissionError):
        run(manifest, deny)
    expired = manifest.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(hours=1)})
    with pytest.raises(ValueError, match="expired"):
        run(expired, lambda: None)
    with pytest.raises(ValueError, match="coverage is incomplete"):
        run(
            manifest,
            lambda: None,
            QuestionChunkResult(
                examined_row_count=9,
                failed_row_count=0,
                unique_input_count=1,
                reused_decision_count=1,
                new_decision_count=0,
            ),
        )
    for update in (
        {"question_config": QuestionConfig(question="A different question?")},
        {"evaluator_version": EVALUATOR_VERSION + 1},
    ):
        with pytest.raises(ValueError, match="do not match"):
            run(manifest.model_copy(update=update), lambda: None)


def test_inference_budget_errors_on_partial_coverage_but_allows_warm_decisions() -> None:
    cache = JevDecisionCache(fakeredis.FakeRedis(), team_id=1)
    runner = QuestionChunkEvaluator(
        cache=cache,
        config=QuestionConfig(question="Is this valid?"),
        model_id="example-model",
        model_revision="immutable-revision-1",
        evaluate=lambda inputs: [0.9] * len(inputs),
        max_inference_inputs=1,
        max_run_seconds=10_000,
    )
    first = runner.run([WeightedInput(text="a", row_count=1)])
    assert first.new_decision_count == 1
    with pytest.raises(RuntimeError, match="inference budget.*incomplete coverage"):
        runner.run([WeightedInput(text="b", row_count=1)])
    assert runner.run([WeightedInput(text="a", row_count=1)]).reused_decision_count == 1


@pytest.mark.parametrize(
    "rows,allowed_rate,status",
    [(0, 0, CheckRunStatus.SKIPPED), (10, 0.1, CheckRunStatus.PASSED), (10, 0, CheckRunStatus.FAILED)],
)
def test_empty_scope_and_failure_rate_equality(rows: int, allowed_rate: float, status: CheckRunStatus) -> None:
    async def source() -> AsyncIterator[WeightedInput]:
        if rows:
            yield WeightedInput(text=None, row_count=1)
            yield WeightedInput(text="valid", row_count=rows - 1)

    store = QuestionManifestStore()
    config = QuestionConfig(question="Is this valid?", max_failure_rate=allowed_rate)
    objects: dict[str, str] = {}
    with (
        patch(
            "posthog.storage.object_storage.write", side_effect=lambda key, content: objects.__setitem__(key, content)
        ),
        patch("posthog.storage.object_storage.read", side_effect=lambda key: objects.get(key)),
    ):
        manifest = async_to_sync(freeze_question_inputs)(
            inputs=source(),
            store=store,
            team_id=1,
            run_id="example-run",
            subject_uuid="example-table",
            model_id="example-model",
            model_revision="immutable-revision-1",
            config=config,
            column_name="description",
        )
        runner = evaluator(
            JevDecisionCache(fakeredis.FakeRedis(), team_id=1),
            lambda inputs: [0.9] * len(inputs),
            max_failure_rate=allowed_rate,
        )
        result = evaluate_question_manifest(
            manifest=manifest,
            store=store,
            evaluator=runner,
            authorize=lambda: None,
            load_checkpoint=lambda index: None,
            save_checkpoint=lambda index, result: result,
        )
    assert result.status == status
    assert result.examined_row_count == rows


@pytest.mark.parametrize("enabled", [True, False])
def test_gateway_access_and_attribution(enabled: bool) -> None:
    team = cast(
        "Team", SimpleNamespace(pk=42, id=42, uuid=UUID(int=42), organization_id=7, api_token="example-api-token")
    )
    with (
        override_settings(
            AI_GATEWAY_URL="https://ai-gateway.example.com/v1",
            AI_GATEWAY_API_KEY="phs_test",
            CLICKHOUSE_USE_HTTP=False,
            CLICKHOUSE_USE_HTTP_PER_TEAM=[],
        ),
        patch("posthog.hogql.transforms.prompt_jev.feature_enabled_or_false", return_value=enabled),
        patch("ee.billing.quota_limiting.is_team_over_ai_credit_budget", return_value=False),
        patch.object(
            httpx.AsyncClient,
            "send",
            new_callable=AsyncMock,
            return_value=httpx.Response(200, json={"model": "example-model", "answers": {"row_0": {"noul": 0.9}}}),
        ) as send,
    ):
        if not enabled:
            with pytest.raises(QueryError, match="not enabled"):
                QuestionGatewayEvaluator(
                    team=team,
                    model_id="example-model",
                    question="Is this valid?",
                    check_id="example-check",
                    run_id="example-run",
                    distinct_id="example-user",
                )
            assert not send.called
            return
        runner = QuestionGatewayEvaluator(
            team=team,
            model_id="example-model",
            question="Is this valid?",
            check_id="example-check",
            run_id="example-run",
            distinct_id="example-user",
        )
        assert runner(["example input"]) == [0.9]
    gateway_request = send.call_args.args[0]
    properties = json.loads(gateway_request.headers["X-PostHog-Properties"])
    assert properties["team_id"] == "42"
    assert properties["data_quality_check_id"] == "example-check"
    assert properties["data_quality_run_id"] == "example-run"
    assert gateway_request.headers["X-PostHog-Trace-Id"] == "example-run"
    assert gateway_request.headers["X-PostHog-Distinct-Id"] == "example-user"
    assert "example input" not in str(gateway_request.headers)
    assert json.loads(gateway_request.content)["model"] == "example-model"
