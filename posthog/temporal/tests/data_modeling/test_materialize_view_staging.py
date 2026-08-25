import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow as pa
from parameterized import parameterized

from posthog.temporal.data_modeling.activities.materialize_view import _CDPRowSink, _stage_person_property_batch

pytestmark = pytest.mark.asyncio


def _sink() -> MagicMock:
    return MagicMock(stage_chunk=AsyncMock(), logger=MagicMock(awarning=AsyncMock()))


def _batch() -> pa.RecordBatch:
    return pa.RecordBatch.from_arrays([pa.array(["a"])], names=["distinct_id"])


def _producer() -> MagicMock:
    return MagicMock(stage_chunk=AsyncMock(), clear=AsyncMock())


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


class TestCDPRowSinkStage:
    @parameterized.expand(
        [
            ("permission_error", PermissionError("Access Denied"), False),
            (
                "s3_access_denied_oserror",
                OSError(
                    "When initiating multiple part upload for key 'chunk_0.parquet' in bucket "
                    "'data-warehouse': AWS Error ACCESS_DENIED during CreateMultipartUpload operation: "
                    "Access Denied (Request ID: ABCDEF)"
                ),
                False,
            ),
            ("other_error", RuntimeError("staging blew up"), True),
        ]
    )
    async def test_stage_reports_only_non_permission_failures(self, _name, error, expect_capture) -> None:
        # A missing write grant on the cdp_producer/ prefix is an anticipated provisioning gap, not a
        # bug — reporting it would page someone for nothing actionable. Any other failure is still a
        # real bug and must keep reaching error tracking.
        producer = _producer()
        producer.stage_chunk.side_effect = error
        sink = _CDPRowSink(producer, MagicMock(awarning=AsyncMock()))
        sink.enabled = True

        with patch("posthog.temporal.data_modeling.activities.materialize_view.capture_exception") as mock_capture:
            await sink.stage(_batch())

        assert mock_capture.called is expect_capture
        assert sink.enabled is False
        producer.clear.assert_awaited_once()
