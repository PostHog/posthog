import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.ai_observability.backend.dataset_export import DatasetExportError, export_dataset_jsonl
from products.ai_observability.backend.dataset_service import (
    DatasetItemMutationResult,
    archive_dataset_item,
    create_dataset,
    create_dataset_item,
    update_dataset_item,
)
from products.ai_observability.backend.models.datasets import Dataset
from products.exports.backend.models.exported_asset import ExportedAsset


class TestDatasetExport(APIBaseTest):
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

    @patch("products.ai_observability.backend.dataset_export.posthog_feature_flag_enabled", return_value=True)
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
        assert asset.content is not None
        rows = [json.loads(line) for line in bytes(asset.content).decode().splitlines()]
        expected_items = sorted(
            [first_result.item, second_result.item],
            key=lambda item: (item.created_at, str(item.id)),
        )
        self.assertEqual([row["item_id"] for row in rows], [str(item.id) for item in expected_items])

        first_row = next(row for row in rows if row["item_id"] == str(first_result.item.id))
        self.assertEqual(first_row["input"], {"question": "Updated"})
        self.assertEqual(first_row["expected_output"], {"answer": ["Keep", "nested", "JSON"]})
        self.assertEqual(first_row["version_id"], str(updated_first.version.id))
        self.assertEqual(first_row["dataset_revision"], pinned_revision)
        self.assertEqual(first_row["dataset_revision_id"], str(second_result.version.dataset_revision_id))
        self.assertEqual(first_row["version_dataset_revision"], updated_first.version.dataset_revision.revision)
        self.assertEqual(first_row["version_dataset_revision_id"], str(updated_first.version.dataset_revision_id))
        self.assertEqual(first_row["client_item_id"], "support-1")
        self.assertFalse(first_row["archived"])
        self.assertNotIn("item_updated_at", first_row)

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
            export_context={"dataset_id": str(dataset.id), "dataset_revision": 1},
        )

        with (
            patch(
                "products.ai_observability.backend.dataset_export.UserAccessControl.check_access_level_for_object",
                return_value=access_allowed,
            ),
            patch(
                "products.ai_observability.backend.dataset_export.posthog_feature_flag_enabled",
                return_value=feature_enabled,
            ),
            self.assertRaisesRegex(DatasetExportError, expected_error),
        ):
            export_dataset_jsonl(asset)

        asset.refresh_from_db()
        self.assertFalse(asset.has_content)
