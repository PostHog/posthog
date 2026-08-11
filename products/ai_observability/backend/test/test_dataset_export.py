import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.storage import object_storage

from products.ai_observability.backend.dataset_export import DatasetExportError, export_dataset_jsonl
from products.ai_observability.backend.dataset_service import (
    DatasetItemMutationResult,
    archive_dataset_item,
    create_dataset,
    create_dataset_item,
    update_dataset_item,
)
from products.ai_observability.backend.models.datasets import Dataset
from products.exports.backend.facade.api import DATASET_EXPORT_KIND, ExportedAsset, RetryableExportError
from products.exports.backend.tasks.failure_handler import EXCEPTIONS_TO_RETRY


class TestDatasetExport(APIBaseTest):
    @staticmethod
    def _read_asset_content(asset: ExportedAsset) -> bytes:
        if asset.content is not None:
            return bytes(asset.content)
        assert asset.content_location is not None
        content = object_storage.read_bytes(asset.content_location)
        assert content is not None
        return content

    def _create_dataset_and_item(self) -> tuple[Dataset, DatasetItemMutationResult]:
        dataset = create_dataset(team=self.team, created_by=self.user, name="Support answers")
        result = create_dataset_item(
            team_id=self.team.id,
            dataset_id=dataset.id,
            created_by=self.user,
            client_item_id="support-1",
            input={"question": "First"},
            expected_output={"answer": "First"},
        )
        return dataset, result

    @patch("products.ai_observability.backend.dataset_export.posthog_feature_flag_value", return_value=True)
    def test_export_uses_the_pinned_revision_with_stable_order_and_nested_json(self, _feature_flag: object) -> None:
        dataset, first_result = self._create_dataset_and_item()
        updated_first = update_dataset_item(
            team_id=self.team.id,
            dataset_id=dataset.id,
            item_id=first_result.item.id,
            created_by=self.user,
            base_version=1,
            input={"question": "Updated"},
            expected_output={"answer": ["Keep", "nested", "JSON"]},
        )
        second_result = create_dataset_item(
            team_id=self.team.id,
            dataset_id=dataset.id,
            created_by=self.user,
            client_item_id="support-2",
            input={"question": "Second"},
        )
        pinned_revision = second_result.version.dataset_revision.revision
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.JSONL,
            export_context={
                "kind": DATASET_EXPORT_KIND,
                "dataset_id": str(dataset.id),
                "dataset_revision": pinned_revision,
                "filename": f"{dataset.name}-r{pinned_revision}",
            },
        )

        archive_dataset_item(
            team_id=self.team.id,
            dataset_id=dataset.id,
            item_id=second_result.item.id,
            created_by=self.user,
            base_version=1,
        )
        export_dataset_jsonl(asset)

        asset.refresh_from_db()
        rows = [json.loads(line) for line in self._read_asset_content(asset).decode().splitlines()]
        expected_items = sorted(
            [first_result.item, second_result.item],
            key=lambda item: (item.created_at, str(item.id)),
        )
        self.assertEqual([row["item_id"] for row in rows], [str(item.id) for item in expected_items])

        first_row = next(row for row in rows if row["item_id"] == str(first_result.item.id))
        self.assertEqual(first_row["input"], {"question": "Updated"})
        self.assertEqual(first_row["expected_output"], {"answer": ["Keep", "nested", "JSON"]})
        self.assertEqual(first_row["version"], updated_first.version.version)
        self.assertEqual(first_row["dataset_revision"], pinned_revision)
        self.assertEqual(first_row["client_item_id"], "support-1")
        self.assertEqual(
            set(first_row),
            {
                "dataset_id",
                "dataset_revision",
                "item_id",
                "client_item_id",
                "version",
                "input",
                "expected_output",
                "source_output",
                "metadata",
                "source_trace_id",
                "source_event_id",
                "source_timestamp",
            },
        )

    @patch("products.ai_observability.backend.dataset_export.posthog_feature_flag_value", return_value=True)
    def test_empty_snapshot_exports_an_empty_file(self, _feature_flag: object) -> None:
        dataset, result = self._create_dataset_and_item()
        archived = archive_dataset_item(
            team_id=self.team.id,
            dataset_id=dataset.id,
            item_id=result.item.id,
            created_by=self.user,
            base_version=1,
        )
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.JSONL,
            export_context={
                "kind": DATASET_EXPORT_KIND,
                "dataset_id": str(dataset.id),
                "dataset_revision": archived.version.dataset_revision.revision,
            },
        )

        export_dataset_jsonl(asset)

        asset.refresh_from_db()
        self.assertTrue(asset.has_content)
        self.assertEqual(self._read_asset_content(asset), b"")

    @patch("products.ai_observability.backend.dataset_export.MAX_DATASET_EXPORT_BYTES", 1)
    @patch("products.ai_observability.backend.dataset_export.posthog_feature_flag_value", return_value=True)
    def test_export_stops_when_the_jsonl_size_limit_is_reached(self, _feature_flag: object) -> None:
        dataset, _result = self._create_dataset_and_item()
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.JSONL,
            export_context={
                "kind": DATASET_EXPORT_KIND,
                "dataset_id": str(dataset.id),
                "dataset_revision": 1,
            },
        )

        with self.assertRaisesRegex(DatasetExportError, "Reduce the number or size of items"):
            export_dataset_jsonl(asset)

        asset.refresh_from_db()
        self.assertFalse(asset.has_content)

    @parameterized.expand(
        [
            ("lost_dataset_access", False, True, "You no longer have access to this dataset."),
            ("feature_disabled", True, False, "Dataset exports are not available for this project."),
        ]
    )
    def test_export_rechecks_access(
        self,
        _name: str,
        access_allowed: bool,
        feature_enabled: bool,
        expected_error: str,
    ) -> None:
        dataset, _result = self._create_dataset_and_item()
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.JSONL,
            export_context={
                "kind": DATASET_EXPORT_KIND,
                "dataset_id": str(dataset.id),
                "dataset_revision": 1,
            },
        )

        with (
            patch(
                "products.ai_observability.backend.dataset_export.UserAccessControl.check_access_level_for_object",
                return_value=access_allowed,
            ),
            patch(
                "products.ai_observability.backend.dataset_export.posthog_feature_flag_value",
                return_value=feature_enabled,
            ),
            self.assertRaisesRegex(DatasetExportError, expected_error),
        ):
            export_dataset_jsonl(asset)

        asset.refresh_from_db()
        self.assertFalse(asset.has_content)

    @patch("products.ai_observability.backend.dataset_export.posthog_feature_flag_value", return_value=None)
    def test_export_retries_when_feature_flag_evaluation_is_unavailable(self, _feature_flag: object) -> None:
        dataset, _result = self._create_dataset_and_item()
        asset = ExportedAsset.objects.create(
            team=self.team,
            created_by=self.user,
            export_format=ExportedAsset.ExportFormat.JSONL,
            export_context={
                "kind": DATASET_EXPORT_KIND,
                "dataset_id": str(dataset.id),
                "dataset_revision": 1,
            },
        )

        with self.assertRaises(RetryableExportError) as error:
            export_dataset_jsonl(asset)

        self.assertIsInstance(error.exception, EXCEPTIONS_TO_RETRY)
