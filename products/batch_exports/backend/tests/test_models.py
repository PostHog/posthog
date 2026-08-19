from django.test import SimpleTestCase

from products.batch_exports.backend.models.batch_export import (
    BatchExport,
    BatchExportOnDemand,
    BatchExportRun,
    batch_export_run_review_path,
)


class TestBatchExportRunReviewPath(SimpleTestCase):
    def test_scheduled_export_links_to_the_live_route(self) -> None:
        run = BatchExportRun(batch_export=BatchExport(id="be-1", team_id=7, name="A batch export", deleted=False))

        assert batch_export_run_review_path(run) == "/project/7/pipeline/batch-exports/be-1"

    def test_deleted_scheduled_export_has_no_page(self) -> None:
        run = BatchExportRun(batch_export=BatchExport(id="be-1", team_id=7, name="A batch export", deleted=True))

        assert batch_export_run_review_path(run) is None

    def test_on_demand_run_has_no_page(self) -> None:
        run = BatchExportRun(batch_export_on_demand=BatchExportOnDemand(id="od-1", team_id=7, model="events"))

        assert batch_export_run_review_path(run) is None
