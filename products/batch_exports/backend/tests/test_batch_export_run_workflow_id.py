import datetime as dt
from uuid import UUID

from django.test import SimpleTestCase

from parameterized import parameterized

from products.batch_exports.backend.models import BatchExport, BatchExportOnDemand, BatchExportRun


class TestBatchExportRunWorkflowId(SimpleTestCase):
    @parameterized.expand(
        [
            ("bounded", True, True, "2026-01-01T00:00:00Z-2026-01-02T00:00:00Z"),
            ("start_only", True, False, "00000000-0000-0000-0000-000000000002"),
            ("end_only", False, True, "00000000-0000-0000-0000-000000000002"),
            ("unbounded", False, False, "00000000-0000-0000-0000-000000000002"),
        ]
    )
    def test_on_demand_workflow_id(self, _name: str, has_start: bool, has_end: bool, expected_suffix: str) -> None:
        parent = BatchExportOnDemand(id=UUID(int=1))
        run = BatchExportRun(
            id=UUID(int=2),
            batch_export_on_demand=parent,
            data_interval_start=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) if has_start else None,
            data_interval_end=dt.datetime(2026, 1, 2, tzinfo=dt.UTC) if has_end else None,
        )

        assert run.workflow_id == f"{parent.id}-{expected_suffix}"

    @parameterized.expand(
        [
            ("bounded", True, True),
            ("start_only", True, False),
            ("end_only", False, True),
            ("unbounded", False, False),
        ]
    )
    def test_scheduled_workflow_id(self, _name: str, has_start: bool, has_end: bool) -> None:
        parent = BatchExport(id=UUID(int=1))
        run = BatchExportRun(
            batch_export=parent,
            data_interval_start=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) if has_start else None,
            data_interval_end=dt.datetime(2026, 1, 2, tzinfo=dt.UTC) if has_end else None,
        )

        if has_end:
            assert run.workflow_id == f"{parent.id}-2026-01-02T00:00:00Z"
        else:
            with self.assertRaisesRegex(ValueError, "Scheduled batch export runs require data_interval_end"):
                _ = run.workflow_id
