import pytest
from unittest.mock import AsyncMock, MagicMock

import pyarrow as pa

from posthog.temporal.data_modeling.activities.materialize_view import _CDPRowSink, _stage_person_property_batch

pytestmark = pytest.mark.asyncio


def _sink() -> MagicMock:
    return MagicMock(stage_chunk=AsyncMock(), logger=MagicMock(awarning=AsyncMock()))


def _batch() -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays([pa.array(["a"])], names=["distinct_id"])


class TestStagePersonPropertyBatch:
    async def test_incremental_staging_failure_fails_the_run(self) -> None:
        # Swallowing this would let the watermark advance past rows that never reached staging, and an
        # incremental run never re-stages them until they change again. It must raise so Temporal
        # retries the window before the watermark is recorded — the import pipeline's sink contract.
        sink = _sink()
        sink.stage_chunk.side_effect = RuntimeError("staging blew up")
        with pytest.raises(RuntimeError, match="staging blew up"):
            await _stage_person_property_batch(sink, 0, _batch(), fatal=True)

    async def test_full_refresh_staging_failure_is_swallowed(self) -> None:
        # A rebuild re-stages every row on its next run, so a single miss is acceptable and must not
        # fail the materialization.
        sink = _sink()
        sink.stage_chunk.side_effect = RuntimeError("staging blew up")

        await _stage_person_property_batch(sink, 0, _batch(), fatal=False)

        sink.logger.awarning.assert_awaited_once()


class TestCDPRowSinkDiscard:
    async def test_disabled_sink_never_clears(self) -> None:
        # Most teams have no subscriber, so the sink stays disabled and nothing is ever staged.
        # A clear() would list a prefix that does not exist and can return AccessDenied, masking the
        # real failure the run hit.
        producer = MagicMock(clear=AsyncMock())
        sink = _CDPRowSink(producer, MagicMock(awarning=AsyncMock()))

        await sink.discard()

        producer.clear.assert_not_awaited()

    async def test_enabled_sink_clears_staged_rows(self) -> None:
        producer = MagicMock(clear=AsyncMock())
        sink = _CDPRowSink(producer, MagicMock(awarning=AsyncMock()))
        sink.enabled = True

        await sink.discard()

        producer.clear.assert_awaited_once()
