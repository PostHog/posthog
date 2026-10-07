import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pyarrow as pa
from pydantic import BaseModel, ConfigDict, Field

from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.printer import prepare_and_print_ast

from posthog.storage import object_storage
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.asyncpa import AsyncRecordBatchReader
from posthog.temporal.common.clickhouse import ChunkBytesAsyncStreamIterator, get_client

from ..facade.enums import CheckRunStatus, SubjectType
from .contracts import SubjectRef
from .jev_cache import EVALUATOR_VERSION
from .jev_question import (
    QuestionChunkEvaluator,
    QuestionChunkResult,
    QuestionConfig,
    WeightedInput,
    question_input_query,
)
from .permissions import sql_denial_context
from .subjects import subject_column_type

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

CHUNK_INPUTS = 128
MAX_INPUT_BYTES = 8192
# Freezing writes to the shared object store before any inference budget applies, so a subject with
# more distinct inputs than a run can evaluate must fail closed rather than stream without a bound.
MAX_FROZEN_INPUTS = 100_000
# Arrow IPC end-of-stream marker: continuation bytes followed by a zero metadata length.
ARROW_END_OF_STREAM_BYTES = 8


class ManifestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str | None
    row_count: int = Field(ge=1)


class ManifestChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    inputs: list[ManifestInput] = Field(max_length=CHUNK_INPUTS)


class QuestionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prefix: str
    team_id: int = Field(gt=0)
    run_id: str
    subject_uuid: str
    model_id: str
    model_revision: str
    evaluator_version: int = Field(ge=1)
    question_config: QuestionConfig
    column_name: str
    chunk_count: int = Field(ge=0)
    examined_row_count: int = Field(ge=0)
    unique_input_count: int = Field(ge=0)
    created_at: datetime
    expires_at: datetime


class QuestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: CheckRunStatus
    examined_row_count: int = Field(ge=0)
    failed_row_count: int = Field(ge=0)
    failure_rate: float | None
    unique_input_count: int = Field(ge=0)
    reused_decision_count: int = Field(ge=0)
    new_decision_count: int = Field(ge=0)
    completed_chunk_count: int = Field(ge=0)
    total_chunk_count: int = Field(ge=0)
    coverage_complete: bool


class QuestionManifestStore:
    def write_chunk(self, prefix: str, index: int, inputs: Sequence[WeightedInput]) -> None:
        chunk = ManifestChunk(inputs=[ManifestInput(text=item.text, row_count=item.row_count) for item in inputs])
        object_storage.write(f"{prefix}/chunks/{index}.json", chunk.model_dump_json())

    def read_chunk(self, manifest: QuestionManifest, index: int) -> list[WeightedInput]:
        if not 0 <= index < manifest.chunk_count:
            raise ValueError("Question manifest chunk is outside the frozen input set.")
        content = object_storage.read(f"{manifest.prefix}/chunks/{index}.json")
        if content is None:
            raise ValueError("Question manifest is incomplete.")
        chunk = ManifestChunk.model_validate_json(content)
        return [WeightedInput(text=item.text, row_count=item.row_count) for item in chunk.inputs]

    def write_manifest(self, manifest: QuestionManifest) -> str:
        key = f"{manifest.prefix}/manifest.json"
        object_storage.write(key, manifest.model_dump_json())
        return key

    def read_manifest(self, key: str, *, team_id: int, run_id: str) -> QuestionManifest:
        content = object_storage.read(key)
        if content is None:
            raise ValueError("Question manifest is unavailable.")
        manifest = QuestionManifest.model_validate_json(content)
        if manifest.team_id != team_id or manifest.run_id != run_id or manifest.expires_at <= datetime.now(UTC):
            raise ValueError("Question manifest does not belong to this run or has expired.")
        return manifest

    def delete(self, manifest: QuestionManifest) -> None:
        for start in range(0, manifest.chunk_count, 128):
            object_storage.delete_objects(
                [
                    f"{manifest.prefix}/chunks/{index}.json"
                    for index in range(start, min(start + 128, manifest.chunk_count))
                ]
            )
        object_storage.delete(f"{manifest.prefix}/manifest.json")


async def freeze_question_inputs(
    *,
    inputs: AsyncIterator[WeightedInput],
    store: QuestionManifestStore,
    team_id: int,
    run_id: str,
    subject_uuid: str,
    model_id: str,
    model_revision: str,
    config: QuestionConfig,
    column_name: str,
    retention_hours: int = 24,
    max_inputs: int = MAX_FROZEN_INPUTS,
) -> QuestionManifest:
    if not model_id.strip() or not model_revision.strip() or retention_hours < 1 or max_inputs < 1:
        raise ValueError("A snapshot needs a pinned model revision and a positive lifetime.")
    config.input_columns(column_name)
    # Attempts use separate prefixes. Only a complete manifest may be published as the run's snapshot.
    prefix = f"data_quality/jev/{team_id}/{uuid4().hex}"
    chunk: list[WeightedInput] = []
    chunks = rows = unique = 0
    try:
        async for item in inputs:
            if item.text is not None and len(item.text.encode()) > MAX_INPUT_BYTES:
                raise ValueError("A question input exceeds 8 KiB; no input was truncated.")
            if chunks * CHUNK_INPUTS + len(chunk) >= max_inputs:
                raise ValueError("The question subject exceeds the limit on frozen inputs.")
            chunk.append(item)
            rows += item.row_count
            unique += item.text is not None
            if len(chunk) == CHUNK_INPUTS:
                await asyncio.to_thread(store.write_chunk, prefix, chunks, chunk)
                chunk = []
                chunks += 1
        if chunk:
            await asyncio.to_thread(store.write_chunk, prefix, chunks, chunk)
            chunks += 1
        created_at = datetime.now(UTC)
        manifest = QuestionManifest(
            prefix=prefix,
            team_id=team_id,
            run_id=run_id,
            subject_uuid=subject_uuid,
            model_id=model_id,
            model_revision=model_revision,
            evaluator_version=EVALUATOR_VERSION,
            question_config=config.model_copy(deep=True),
            column_name=column_name,
            chunk_count=chunks,
            examined_row_count=rows,
            unique_input_count=unique,
            created_at=created_at,
            expires_at=created_at + timedelta(hours=retention_hours),
        )
        await asyncio.to_thread(store.write_manifest, manifest)
        return manifest
    except BaseException:
        # A failed scan must never publish a partial manifest. Cleanup is best effort; expired
        # attempt prefixes also need the object store's lifecycle policy before production rollout.
        for index in range(chunks + 1):
            try:
                await asyncio.to_thread(object_storage.delete, f"{prefix}/chunks/{index}.json")
            except Exception:
                pass
        raise


def prepare_warehouse_question_inputs(
    team: "Team", user: "User", subject: SubjectRef, config: QuestionConfig, column_name: str
) -> tuple[str, HogQLContext]:
    if not subject.exists or subject.subject_type != SubjectType.TABLE:
        raise ValueError("The initial question executor supports resolved warehouse tables only.")
    if config.lookback_hours is not None:
        raise ValueError("Warehouse tables have no lookback time column.")
    for name in config.input_columns(column_name):
        if subject_column_type(team.id, subject.subject_type, subject.subject_uuid, name) is None:
            raise ValueError("A selected question field is not available on the subject.")
    modifiers = create_default_modifiers_for_team(team)
    database = Database.create_for(team=team, user=user, modifiers=modifiers)
    if not sql_denial_context(team.id, database).readable.contains(subject.subject_type, subject.subject_uuid):
        raise ValueError("The executing user cannot read the question check's subject.")
    context = HogQLContext(
        team=team,
        team_id=team.id,
        user=user,
        database=database,
        modifiers=modifiers,
        enable_select_queries=True,
        limit_top_select=False,
        output_format="ArrowStream",
    )
    # Overflow must throw: even a cleanly terminated partial stream is incomplete coverage.
    settings = HogQLGlobalSettings(max_execution_time=300, timeout_overflow_mode="throw", read_overflow_mode="throw")
    query = question_input_query(subject, config, column_name)
    sql, prepared = prepare_and_print_ast(query, context=context, dialect="clickhouse", settings=settings)
    if prepared is None:
        raise ValueError("The question input query could not be prepared.")
    return sql, context


class _ResponseBytes:
    def __init__(self, chunks: AsyncIterator[bytes]) -> None:
        self.chunks = chunks
        self.received = 0
        self.ended = False

    def __aiter__(self) -> "_ResponseBytes":
        return self

    async def __anext__(self) -> bytes:
        try:
            chunk = await anext(self.chunks)
        except StopAsyncIteration:
            self.ended = True
            raise
        self.received += len(chunk)
        return chunk


async def strict_arrow_batches(chunks: AsyncIterator[bytes]) -> AsyncIterator[pa.RecordBatch]:
    """Arrow batches from a response that must reach the end-of-stream marker and carry nothing after it."""
    body = _ResponseBytes(chunks)
    reader = AsyncRecordBatchReader(body)
    async for batch in reader:
        yield batch
    # The shared reader also stops quietly when the response ends between or inside messages.
    if body.ended:
        raise ValueError("The question input stream ended before its end marker.")
    async for _ in body:
        pass
    if body.received != reader.bytes_consumed + ARROW_END_OF_STREAM_BYTES:
        raise ValueError("The question input stream has data after its end marker.")


async def warehouse_question_inputs(
    *, team: "Team", user: "User", subject: SubjectRef, config: QuestionConfig, column_name: str
) -> AsyncIterator[WeightedInput]:
    sql, context = await database_sync_to_async_pool(prepare_warehouse_question_inputs)(
        team, user, subject, config, column_name
    )
    async with get_client(
        team_id=team.id,
        max_block_size=CHUNK_INPUTS,
        result_overflow_mode="throw",
        group_by_overflow_mode="throw",
        max_result_rows=0,
        max_result_bytes=0,
        # toJSONString writes NaN and infinities as null by default, which merges them with SQL NULL in row inputs.
        output_format_json_quote_denormals=1,
    ) as client:
        async with client.apost_query(
            sql,
            query_parameters=context.values,
            query_id=None,
            external_tables=list(context.external_tables.values()),
        ) as response:
            async for batch in strict_arrow_batches(ChunkBytesAsyncStreamIterator(response.content)):
                for item in batch.to_pylist():
                    yield WeightedInput(text=item["input"], row_count=item["row_count"])


def evaluate_question_manifest(
    *,
    manifest: QuestionManifest,
    store: QuestionManifestStore,
    evaluator: QuestionChunkEvaluator,
    authorize: Callable[[], None],
    load_checkpoint: Callable[[int], QuestionChunkResult | None],
    save_checkpoint: Callable[[int, QuestionChunkResult], QuestionChunkResult],
) -> QuestionResult:
    """Checkpoint callbacks must persist the first result atomically under (run, chunk)."""
    if (
        manifest.team_id != evaluator.cache.team_id
        or manifest.model_id != evaluator.model_id
        or manifest.model_revision != evaluator.model_revision
        or manifest.evaluator_version != EVALUATOR_VERSION
        or manifest.question_config != evaluator.config
    ):
        raise ValueError("The frozen run and decision evaluator do not match.")
    examined = failed = unique = reused = new = completed = 0
    authorize()
    if manifest.expires_at <= datetime.now(UTC):
        raise ValueError("Question manifest expired with incomplete coverage.")
    for index in range(manifest.chunk_count):
        if manifest.expires_at <= datetime.now(UTC):
            raise ValueError("Question manifest expired with incomplete coverage.")
        authorize()
        result = load_checkpoint(index)
        if result is None:
            result = save_checkpoint(index, evaluator.run(store.read_chunk(manifest, index)))
        examined += result.examined_row_count
        failed += result.failed_row_count
        unique += result.unique_input_count
        reused += result.reused_decision_count
        new += result.new_decision_count
        completed += 1
    if examined != manifest.examined_row_count or unique != manifest.unique_input_count:
        raise ValueError("Question manifest coverage is incomplete.")
    rate = failed / examined if examined else None
    status = (
        CheckRunStatus.SKIPPED
        if rate is None
        else (CheckRunStatus.PASSED if rate <= evaluator.config.max_failure_rate else CheckRunStatus.FAILED)
    )
    return QuestionResult(
        status=status,
        examined_row_count=examined,
        failed_row_count=failed,
        failure_rate=rate,
        unique_input_count=unique,
        reused_decision_count=reused,
        new_decision_count=new,
        completed_chunk_count=completed,
        total_chunk_count=manifest.chunk_count,
        coverage_complete=True,
    )
