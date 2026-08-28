from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import RestrictedError
from django.utils.timezone import now

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.ai_observability.backend.api.dataset_exports import DATASET_EXPORT_STUCK_MESSAGE
from products.ai_observability.backend.dataset_service import create_dataset
from products.ai_observability.backend.models.datasets import Dataset, DatasetItem, DatasetItemVersion, DatasetRevision
from products.exports.backend.facade.api import DATASET_EXPORT_KIND, ExportedAsset


class TestDatasetsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_flag_patch = patch(
            "posthog.permissions.posthog_feature_flag_enabled",
            return_value=True,
        )
        feature_flag_patch.start()
        self.addCleanup(feature_flag_patch.stop)
        self.datasets_url = f"/api/environments/{self.team.id}/datasets/"
        self.items_url = f"/api/environments/{self.team.id}/dataset_items/"

    def _create_dataset(self, name: str = "Support answers") -> dict:
        response = self.client.post(
            self.datasets_url,
            {
                "name": name,
                "description": "Representative support requests",
                "metadata": {"owner": "support"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def _create_item(self, dataset_id: str, **overrides: object) -> dict:
        payload: dict[str, object] = {
            "dataset": dataset_id,
            "input": {"question": "How do I reset my password?"},
            "expected_output": {"answer": "Open account settings."},
            "metadata": {"language": "en"},
        }
        payload.update(overrides)
        response = self.client.post(self.items_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data

    def test_feature_flag_gates_the_api_server_side(self) -> None:
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            response = self.client.get(self.datasets_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dataset_lifecycle_and_name_uniqueness(self) -> None:
        dataset = self._create_dataset()

        duplicate_response = self.client.post(
            self.datasets_url,
            {"name": "  Support answers  "},
            format="json",
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(duplicate_response.data["code"], "dataset_name_conflict")

        archive_response = self.client.post(f"{self.datasets_url}{dataset['id']}/archive/")
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertTrue(archive_response.data["archived"])

        active_list_response = self.client.get(self.datasets_url)
        self.assertEqual(active_list_response.data["results"], [])

        archived_list_response = self.client.get(self.datasets_url, {"archived": "true"})
        self.assertEqual([result["id"] for result in archived_list_response.data["results"]], [dataset["id"]])

        retrieve_response = self.client.get(f"{self.datasets_url}{dataset['id']}/")
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertIn("user_access_level", retrieve_response.data)

        blocked_item_response = self.client.post(
            self.items_url,
            {"dataset": dataset["id"], "input": "blocked"},
            format="json",
        )
        self.assertEqual(blocked_item_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(blocked_item_response.data["code"], "dataset_archived")

        restore_response = self.client.post(f"{self.datasets_url}{dataset['id']}/restore/")
        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.assertFalse(restore_response.data["archived"])

    def test_dataset_list_filters_by_comma_separated_ids(self) -> None:
        first_dataset = self._create_dataset("First dataset")
        second_dataset = self._create_dataset("Second dataset")
        self._create_dataset("Excluded dataset")

        response = self.client.get(
            self.datasets_url,
            {"id__in": f"{first_dataset['id']},{second_dataset['id']}"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(
            [result["id"] for result in response.data["results"]],
            [first_dataset["id"], second_dataset["id"]],
        )

    def test_dataset_list_rejects_invalid_ids(self) -> None:
        response = self.client.get(self.datasets_url, {"id__in": "not-a-uuid"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("false", False),
            ("zero", 0),
            ("empty_string", ""),
            ("empty_list", []),
            ("empty_object", {}),
        ]
    )
    def test_item_input_accepts_any_non_null_json(self, _name: str, input_value: object) -> None:
        dataset = self._create_dataset(f"JSON {_name}")

        item = self._create_item(dataset["id"], input=input_value)

        self.assertEqual(item["input"], input_value)

    def test_item_create_handles_existing_client_item_id(self) -> None:
        dataset = self._create_dataset()
        payload = {
            "dataset": dataset["id"],
            "client_item_id": "trace:abc:event:def",
            "input": ["hello"],
            "source_output": ["world"],
            "source_trace_id": "abc",
            "source_event_id": "def",
            "source_timestamp": "2026-07-30T12:00:00Z",
        }

        first_response = self.client.post(self.items_url, payload, format="json")
        retry_response = self.client.post(self.items_url, payload, format="json")

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(retry_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retry_response.data["id"], first_response.data["id"])
        self.assertEqual(retry_response.data["client_item_id"], payload["client_item_id"])
        self.assertEqual(
            DatasetRevision.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(),
            1,
        )

        conflicting_response = self.client.post(
            self.items_url,
            {**payload, "input": ["different"]},
            format="json",
        )
        self.assertEqual(conflicting_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(conflicting_response.data["code"], "client_item_id_conflict")

        archive_response = self.client.post(
            f"{self.items_url}{first_response.data['id']}/archive/",
            {"base_version": 1},
            format="json",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)

        archived_retry_response = self.client.post(self.items_url, payload, format="json")

        self.assertEqual(archived_retry_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(archived_retry_response.data["code"], "client_item_id_conflict")
        self.assertEqual(str(archived_retry_response.data["current_item_id"]), first_response.data["id"])
        self.assertEqual(
            DatasetItem.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(),
            1,
        )
        self.assertEqual(
            DatasetRevision.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(),
            2,
        )

    def test_client_item_id_idempotency_preserves_json_types(self) -> None:
        dataset = self._create_dataset()
        payload = {
            "dataset": dataset["id"],
            "client_item_id": "typed-input",
            "input": {"value": True},
        }
        self.assertEqual(
            self.client.post(self.items_url, payload, format="json").status_code,
            status.HTTP_201_CREATED,
        )

        response = self.client.post(
            self.items_url,
            {**payload, "input": {"value": 1}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["code"], "client_item_id_conflict")

    def test_update_creates_history_and_preserves_source_fields(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(
            dataset["id"],
            source_output={"actual": "old"},
            source_trace_id="trace-id",
            source_event_id="event-id",
            source_timestamp="2026-07-30T12:00:00Z",
        )

        update_response = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {
                "base_version": item["version"],
                "input": {"question": "Updated"},
                "expected_output": None,
                "metadata": {},
            },
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["version"], 2)
        self.assertEqual(update_response.data["dataset_revision"], 2)
        self.assertEqual(update_response.data["expected_output"], None)
        self.assertEqual(update_response.data["source_output"], {"actual": "old"})
        self.assertEqual(update_response.data["source_trace_id"], "trace-id")
        self.assertEqual(update_response.data["metadata"], {})

        versions = list(
            DatasetItemVersion.objects.for_team(self.team.id).filter(dataset_item_id=item["id"]).order_by("version")
        )
        self.assertEqual(
            [version.input for version in versions],
            [{"question": "How do I reset my password?"}, {"question": "Updated"}],
        )
        self.assertEqual(versions[0].expected_output, {"answer": "Open account settings."})

        immutable_source_response = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {"base_version": 2, "source_output": "replacement"},
            format="json",
        )
        self.assertEqual(immutable_source_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_stale_update_does_not_create_a_revision(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        first_update = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {"base_version": 1, "input": "new"},
            format="json",
        )
        self.assertEqual(first_update.status_code, status.HTTP_200_OK)

        stale_update = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {"base_version": 1, "input": "stale"},
            format="json",
        )
        self.assertEqual(stale_update.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(stale_update.data["code"], "stale_version")
        self.assertEqual(stale_update.data["current_version"], 2)
        self.assertEqual(
            DatasetRevision.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(),
            2,
        )

    def test_unchanged_update_does_not_create_a_revision(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        response = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {
                "base_version": 1,
                "input": item["input"],
                "expected_output": item["expected_output"],
                "metadata": item["metadata"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["version"], 1)
        self.assertEqual(
            DatasetRevision.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(),
            1,
        )

    def test_archive_and_restore_create_versions_with_explicit_transitions(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"], input="original")
        update_response = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {"base_version": 1, "input": "edited"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        archive_response = self.client.post(
            f"{self.items_url}{item['id']}/archive/",
            {"base_version": 2},
            format="json",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertTrue(archive_response.data["archived"])
        self.assertEqual(archive_response.data["version"], 3)

        active_list = self.client.get(self.items_url, {"dataset": dataset["id"]})
        archived_list = self.client.get(
            self.items_url,
            {"dataset": dataset["id"], "archived": "true"},
        )
        self.assertEqual(active_list.data["results"], [])
        self.assertEqual([result["id"] for result in archived_list.data["results"]], [item["id"]])

        duplicate_archive = self.client.post(
            f"{self.items_url}{item['id']}/archive/",
            {"base_version": 3},
            format="json",
        )
        self.assertEqual(duplicate_archive.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(duplicate_archive.data["code"], "dataset_item_archived")

        restore_response = self.client.post(
            f"{self.items_url}{item['id']}/restore/",
            {"base_version": 3, "source_version": 1},
            format="json",
        )
        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.assertFalse(restore_response.data["archived"])
        self.assertEqual(restore_response.data["input"], "original")
        self.assertEqual(restore_response.data["version"], 4)

        duplicate_restore = self.client.post(
            f"{self.items_url}{item['id']}/restore/",
            {"base_version": 4},
            format="json",
        )
        self.assertEqual(duplicate_restore.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(duplicate_restore.data["code"], "dataset_item_active")

    def test_revision_list_reconstructs_exact_snapshots(self) -> None:
        dataset = self._create_dataset()
        first_item = self._create_item(dataset["id"], input="first-v1")
        first_update = self.client.patch(
            f"{self.items_url}{first_item['id']}/",
            {"base_version": 1, "input": "first-v2"},
            format="json",
        )
        self.assertEqual(first_update.status_code, status.HTTP_200_OK)
        second_item = self._create_item(dataset["id"], input="second")
        archive_response = self.client.post(
            f"{self.items_url}{first_item['id']}/archive/",
            {"base_version": 2},
            format="json",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)

        revision_one = self.client.get(
            self.items_url,
            {"dataset": dataset["id"], "revision": 1},
        )
        self.assertEqual(
            [(result["id"], result["input"]) for result in revision_one.data["results"]],
            [(first_item["id"], "first-v1")],
        )

        revision_three = self.client.get(
            self.items_url,
            {"dataset": dataset["id"], "revision": 3},
        )
        revision_three_items = {result["id"]: result["input"] for result in revision_three.data["results"]}
        self.assertEqual(
            revision_three_items,
            {first_item["id"]: "first-v2", second_item["id"]: "second"},
        )

        current_active = self.client.get(self.items_url, {"dataset": dataset["id"]})
        self.assertEqual([result["id"] for result in current_active.data["results"]], [second_item["id"]])

        revision_four_archived = self.client.get(
            self.items_url,
            {"dataset": dataset["id"], "revision": 4, "archived": "true"},
        )
        self.assertEqual(
            [result["id"] for result in revision_four_archived.data["results"]],
            [first_item["id"]],
        )

        item_at_revision_one = self.client.get(
            f"{self.items_url}{first_item['id']}/",
            {"revision": 1},
        )
        item_at_revision_three = self.client.get(
            f"{self.items_url}{first_item['id']}/",
            {"revision": 3},
        )
        missing_item_revision = self.client.get(
            f"{self.items_url}{second_item['id']}/",
            {"revision": 1},
        )

        self.assertEqual(item_at_revision_one.status_code, status.HTTP_200_OK)
        self.assertEqual(item_at_revision_one.data["input"], "first-v1")
        self.assertEqual(item_at_revision_three.status_code, status.HTTP_200_OK)
        self.assertEqual(item_at_revision_three.data["input"], "first-v2")
        self.assertEqual(missing_item_revision.status_code, status.HTTP_404_NOT_FOUND)

    def test_inconsistent_item_version_ownership_is_not_readable(self) -> None:
        accessible_dataset = self._create_dataset("Accessible dataset")
        other_dataset = self._create_dataset("Other dataset")
        item = self._create_item(other_dataset["id"])
        item_version = DatasetItemVersion.objects.unscoped().filter(id=item["version_id"])
        item_version.update(dataset_id=accessible_dataset["id"])

        try:
            list_response = self.client.get(self.items_url, {"dataset": accessible_dataset["id"]})
            retrieve_response = self.client.get(f"{self.items_url}{item['id']}/")

            self.assertEqual(list_response.status_code, status.HTTP_200_OK)
            self.assertEqual(list_response.data["results"], [])
            self.assertEqual(retrieve_response.status_code, status.HTTP_404_NOT_FOUND)
        finally:
            item_version.update(dataset_id=other_dataset["id"])

    @parameterized.expand(
        [
            ("trace_without_timestamp", {"source_trace_id": "trace-id"}),
            ("timestamp_without_trace", {"source_timestamp": "2026-07-30T12:00:00Z"}),
            ("event_without_trace", {"source_event_id": "event-id"}),
        ]
    )
    def test_provenance_requires_a_retrievable_trace_reference(
        self,
        _name: str,
        provenance: dict[str, str],
    ) -> None:
        dataset = self._create_dataset(f"Provenance {_name}")

        response = self.client.post(
            self.items_url,
            {"dataset": dataset["id"], "input": "input", **provenance},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_required_filters_and_concurrency_fields_are_enforced(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        list_response = self.client.get(self.items_url)
        update_response = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {"input": "missing base version"},
            format="json",
        )

        self.assertEqual(list_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(update_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(update_response.data["attr"], "base_version")

    def test_cross_team_dataset_and_item_ids_are_not_visible(self) -> None:
        other_team = self.create_team_with_organization(self.organization)
        other_dataset = create_dataset(
            team=other_team,
            created_by=self.user,
            name="Other team's dataset",
        )

        dataset_response = self.client.get(f"{self.datasets_url}{other_dataset.id}/")
        item_list_response = self.client.get(self.items_url, {"dataset": str(other_dataset.id)})

        self.assertEqual(dataset_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(item_list_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_datasets_are_isolated_to_the_exact_environment_team_id(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="Child environment",
        )
        sibling_team = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="Sibling environment",
        )
        parent_dataset = self._create_dataset("Per-environment dataset")

        child_response = self.client.post(
            f"/api/environments/{child_team.id}/datasets/",
            {"name": "Per-environment dataset"},
            format="json",
        )
        sibling_response = self.client.post(
            f"/api/environments/{sibling_team.id}/datasets/",
            {"name": "Per-environment dataset"},
            format="json",
        )

        self.assertEqual(child_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sibling_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Dataset.objects.unscoped().get(id=child_response.data["id"]).team_id,
            child_team.id,
        )
        self.assertEqual(
            Dataset.objects.unscoped().get(id=sibling_response.data["id"]).team_id,
            sibling_team.id,
        )
        child_item_response = self.client.post(
            f"/api/environments/{child_team.id}/dataset_items/",
            {"dataset": child_response.data["id"], "input": "child input"},
            format="json",
        )
        self.assertEqual(child_item_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            [
                DatasetItem.objects.unscoped().get(id=child_item_response.data["id"]).team_id,
                DatasetItemVersion.objects.unscoped().get(id=child_item_response.data["version_id"]).team_id,
                DatasetRevision.objects.unscoped().get(id=child_item_response.data["dataset_revision_id"]).team_id,
            ],
            [child_team.id] * 3,
        )
        self.assertEqual(
            str(DatasetItemVersion.objects.unscoped().get(id=child_item_response.data["version_id"]).dataset_id),
            child_response.data["id"],
        )

        parent_list = self.client.get(self.datasets_url)
        child_list = self.client.get(f"/api/environments/{child_team.id}/datasets/")
        sibling_list = self.client.get(f"/api/environments/{sibling_team.id}/datasets/")

        self.assertEqual([dataset["id"] for dataset in parent_list.data["results"]], [parent_dataset["id"]])
        self.assertEqual([dataset["id"] for dataset in child_list.data["results"]], [child_response.data["id"]])
        self.assertEqual(
            [dataset["id"] for dataset in sibling_list.data["results"]],
            [sibling_response.data["id"]],
        )

    def test_child_scoped_api_key_cannot_access_parent_datasets_through_child_route(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization,
            parent_team=self.team,
            name="Child environment",
        )
        parent_dataset = self._create_dataset("Parent dataset")
        child_response = self.client.post(
            f"/api/environments/{child_team.id}/datasets/",
            {"name": "Child dataset"},
            format="json",
        )
        self.assertEqual(child_response.status_code, status.HTTP_201_CREATED)

        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="child-scoped",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["dataset:read"],
            scoped_teams=[child_team.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key_value}")

        child_dataset_response = self.client.get(
            f"/api/environments/{child_team.id}/datasets/{child_response.data['id']}/"
        )
        parent_dataset_response = self.client.get(f"/api/environments/{child_team.id}/datasets/{parent_dataset['id']}/")

        self.assertEqual(child_dataset_response.status_code, status.HTTP_200_OK)
        self.assertEqual(parent_dataset_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_put_and_delete_are_not_available(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        responses = [
            self.client.put(f"{self.datasets_url}{dataset['id']}/", {"name": "No"}, format="json"),
            self.client.delete(f"{self.datasets_url}{dataset['id']}/"),
            self.client.put(
                f"{self.items_url}{item['id']}/",
                {"base_version": 1, "input": "No"},
                format="json",
            ),
            self.client.delete(f"{self.items_url}{item['id']}/"),
        ]

        self.assertEqual(
            [response.status_code for response in responses],
            [status.HTTP_405_METHOD_NOT_ALLOWED] * 4,
        )

    def test_versions_endpoint_returns_immutable_history(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"], input="v1")
        update_response = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {"base_version": 1, "input": "v2"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        response = self.client.get(
            f"{self.items_url}{item['id']}/versions/",
            {"limit": 1},
        )
        next_page_response = self.client.get(
            f"{self.items_url}{item['id']}/versions/",
            {"limit": 1, "offset": 1},
        )
        revisions_response = self.client.get(
            f"{self.datasets_url}{dataset['id']}/revisions/",
            {"limit": 1},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            [(result["version"], result["input"]) for result in response.data["results"]],
            [(2, "v2")],
        )
        self.assertEqual(
            [(result["version"], result["input"]) for result in next_page_response.data["results"]],
            [(1, "v1")],
        )
        self.assertEqual(revisions_response.data["count"], 2)
        self.assertEqual(
            [result["revision"] for result in revisions_response.data["results"]],
            [2],
        )
        self.assertEqual(
            str(DatasetItem.objects.for_team(self.team.id).get(id=item["id"]).current_version_id),
            update_response.data["version_id"],
        )
        self.assertEqual(
            str(Dataset.objects.for_team(self.team.id).get(id=dataset["id"]).current_revision_id),
            update_response.data["dataset_revision_id"],
        )

    def test_current_pointers_recover_from_immutable_history(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"], input="v1")
        Dataset.objects.for_team(self.team.id).filter(id=dataset["id"]).update(current_revision=None)
        DatasetItem.objects.for_team(self.team.id).filter(id=item["id"]).update(current_version=None)

        dataset_response = self.client.get(f"{self.datasets_url}{dataset['id']}/")
        item_response = self.client.get(f"{self.items_url}{item['id']}/")
        update_response = self.client.patch(
            f"{self.items_url}{item['id']}/",
            {"base_version": 1, "input": "v2"},
            format="json",
        )

        self.assertEqual(dataset_response.status_code, status.HTTP_200_OK)
        self.assertEqual(dataset_response.data["current_revision"], 1)
        self.assertEqual(item_response.status_code, status.HTTP_200_OK)
        self.assertEqual(item_response.data["version"], 1)
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["version"], 2)
        self.assertEqual(update_response.data["dataset_revision"], 2)
        self.assertEqual(
            str(Dataset.objects.for_team(self.team.id).get(id=dataset["id"]).current_revision_id),
            update_response.data["dataset_revision_id"],
        )
        self.assertEqual(
            str(DatasetItem.objects.for_team(self.team.id).get(id=item["id"]).current_version_id),
            update_response.data["version_id"],
        )

    def test_history_deletion_requires_deleting_the_dataset(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])
        revision = DatasetRevision.objects.for_team(self.team.id).get(id=item["dataset_revision_id"])
        version = DatasetItemVersion.objects.for_team(self.team.id).get(id=item["version_id"])

        with self.assertRaises(RestrictedError):
            revision.delete()
        with self.assertRaises(RestrictedError):
            version.delete()

        Dataset.objects.for_team(self.team.id).get(id=dataset["id"]).delete()

        self.assertFalse(DatasetRevision.objects.for_team(self.team.id).filter(id=revision.id).exists())
        self.assertFalse(DatasetItemVersion.objects.for_team(self.team.id).filter(id=version.id).exists())

    def test_personal_api_key_scopes_cover_custom_actions(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])
        read_key = self.create_personal_api_key_with_scopes(["dataset:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {read_key}")

        with patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock):
            export_response = self.client.post(
                f"{self.datasets_url}{dataset['id']}/exports/",
                {},
                format="json",
            )
        read_responses = [
            self.client.get(f"{self.datasets_url}{dataset['id']}/revisions/"),
            self.client.get(f"{self.items_url}{item['id']}/versions/"),
            export_response,
        ]
        blocked_write_responses = [
            self.client.post(f"{self.datasets_url}{dataset['id']}/archive/"),
            self.client.post(
                f"{self.items_url}{item['id']}/archive/",
                {"base_version": 1},
                format="json",
            ),
        ]

        self.assertEqual(
            [response.status_code for response in read_responses],
            [status.HTTP_200_OK, status.HTTP_200_OK, status.HTTP_201_CREATED],
        )
        self.assertEqual(
            [response.status_code for response in blocked_write_responses],
            [status.HTTP_403_FORBIDDEN] * 2,
        )

        write_key = self.create_personal_api_key_with_scopes(["dataset:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {write_key}")

        item_archive_response = self.client.post(
            f"{self.items_url}{item['id']}/archive/",
            {"base_version": 1},
            format="json",
        )
        item_restore_response = self.client.post(
            f"{self.items_url}{item['id']}/restore/",
            {"base_version": 2},
            format="json",
        )
        dataset_archive_response = self.client.post(f"{self.datasets_url}{dataset['id']}/archive/")
        dataset_restore_response = self.client.post(f"{self.datasets_url}{dataset['id']}/restore/")

        self.assertEqual(
            [
                item_archive_response.status_code,
                item_restore_response.status_code,
                dataset_archive_response.status_code,
                dataset_restore_response.status_code,
            ],
            [status.HTTP_200_OK] * 4,
        )

    def test_database_constraints_reject_invalid_json_and_provenance(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        with self.assertRaises(IntegrityError), transaction.atomic():
            Dataset.objects.for_team(self.team.id).filter(id=dataset["id"]).update(metadata=[])

        with self.assertRaises(IntegrityError), transaction.atomic():
            DatasetItemVersion.objects.for_team(self.team.id).filter(id=item["version_id"]).update(
                source_trace_id="trace-without-timestamp"
            )

    def test_database_constraints_reject_inconsistent_version_ownership(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])
        other_dataset = self._create_dataset("Other dataset")

        with self.assertRaises(IntegrityError), transaction.atomic():
            DatasetItemVersion.objects.for_team(self.team.id).filter(id=item["version_id"]).update(
                dataset_id=other_dataset["id"]
            )
            connection.check_constraints([DatasetItemVersion._meta.db_table])

    def test_dataset_limit_counts_archived_datasets(self) -> None:
        with patch("products.ai_observability.backend.dataset_service.MAX_DATASETS_PER_TEAM", 1):
            dataset = self._create_dataset()
            self.client.post(f"{self.datasets_url}{dataset['id']}/archive/")
            response = self.client.post(self.datasets_url, {"name": "Over the limit"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data,
            {
                "code": "limit_reached",
                "detail": "No more datasets can be added to this project. The limit is 1. Contact support if you need more.",
                "resource": "datasets",
                "current_count": 1,
                "limit": 1,
            },
        )
        self.assertEqual(Dataset.objects.for_team(self.team.id).count(), 1)

    def test_item_limit_counts_archived_items_without_creating_a_revision(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])
        archive_response = self.client.post(
            f"{self.items_url}{item['id']}/archive/",
            {"base_version": 1},
            format="json",
        )
        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)

        with patch("products.ai_observability.backend.dataset_service.MAX_ITEMS_PER_DATASET", 1):
            response = self.client.post(
                self.items_url,
                {"dataset": dataset["id"], "input": "Over the limit"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["resource"], "dataset_items")
        self.assertEqual(response.data["current_count"], 1)
        self.assertEqual(response.data["limit"], 1)
        self.assertEqual(DatasetItem.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(), 1)
        self.assertEqual(DatasetRevision.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(), 2)

    def test_version_limit_does_not_create_a_partial_revision(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        with patch("products.ai_observability.backend.dataset_service.MAX_VERSIONS_PER_ITEM", 1):
            response = self.client.patch(
                f"{self.items_url}{item['id']}/",
                {"base_version": 1, "input": "Over the limit"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["resource"], "dataset_item_versions")
        self.assertEqual(response.data["current_count"], 1)
        self.assertEqual(response.data["limit"], 1)
        self.assertEqual(
            DatasetRevision.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(),
            1,
        )
        self.assertEqual(
            DatasetItemVersion.objects.for_team(self.team.id).filter(dataset_item_id=item["id"]).count(),
            1,
        )

    def test_archive_reserves_the_final_version_slot_for_restore(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        with patch("products.ai_observability.backend.dataset_service.MAX_VERSIONS_PER_ITEM", 2):
            response = self.client.post(
                f"{self.items_url}{item['id']}/archive/",
                {"base_version": 1},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data,
            {
                "code": "limit_reached",
                "detail": "This dataset item cannot be archived because the last version slot is reserved for restoring it. The limit is 2. Create a new item to continue.",
                "resource": "dataset_item_versions",
                "current_count": 1,
                "limit": 2,
            },
        )
        self.assertEqual(DatasetRevision.objects.for_team(self.team.id).filter(dataset_id=dataset["id"]).count(), 1)
        current_item = self.client.get(f"{self.items_url}{item['id']}/")
        self.assertEqual(current_item.status_code, status.HTTP_200_OK)
        self.assertFalse(current_item.data["archived"])
        self.assertEqual(current_item.data["version"], 1)

    def test_restore_can_use_the_reserved_final_version_slot(self) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        with patch("products.ai_observability.backend.dataset_service.MAX_VERSIONS_PER_ITEM", 3):
            archive_response = self.client.post(
                f"{self.items_url}{item['id']}/archive/",
                {"base_version": 1},
                format="json",
            )
            restore_response = self.client.post(
                f"{self.items_url}{item['id']}/restore/",
                {"base_version": 2},
                format="json",
            )

        self.assertEqual(archive_response.status_code, status.HTTP_200_OK)
        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        self.assertFalse(restore_response.data["archived"])
        self.assertEqual(restore_response.data["version"], 3)
        self.assertEqual(
            DatasetItemVersion.objects.for_team(self.team.id).filter(dataset_item_id=item["id"]).count(),
            3,
        )

    def test_dataset_list_caps_requested_page_size(self) -> None:
        with patch("products.ai_observability.backend.api.datasets.DatasetPagination.max_limit", 2):
            for index in range(3):
                create_dataset(
                    team=self.team,
                    created_by=self.user,
                    name=f"Dataset {index}",
                )
            response = self.client.get(self.datasets_url, {"limit": 10_000})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)

    def test_dataset_item_list_caps_requested_page_size(self) -> None:
        dataset = self._create_dataset()
        with patch("products.ai_observability.backend.api.datasets.DatasetItemPagination.max_limit", 2):
            for index in range(3):
                self._create_item(dataset["id"], input=index)
            response = self.client.get(
                self.items_url,
                {"dataset": dataset["id"], "limit": 10_000},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_dataset_export_pins_revision_and_scopes_status_and_content(self, async_connect: AsyncMock) -> None:
        dataset = self._create_dataset()
        first_item = self._create_item(dataset["id"], input={"question": "First"})

        create_response = self.client.post(
            f"{self.datasets_url}{dataset['id']}/exports/",
            {},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["status"], "pending")
        self.assertEqual(create_response.data["dataset_revision"], first_item["dataset_revision"])
        self.assertEqual(
            set(create_response.data),
            {"id", "status", "dataset_revision", "filename", "created_at", "expires_after", "exception"},
        )

        async_connect.return_value.start_workflow.assert_awaited_once()

        self._create_item(dataset["id"], input={"question": "Later"})
        export_id = create_response.data["id"]
        status_response = self.client.get(f"{self.datasets_url}{dataset['id']}/exports/{export_id}/")
        self.assertEqual(status_response.status_code, status.HTTP_200_OK)
        self.assertEqual(status_response.data["dataset_revision"], first_item["dataset_revision"])

        other_dataset = self._create_dataset("Other dataset")
        mismatched_parent_response = self.client.get(f"{self.datasets_url}{other_dataset['id']}/exports/{export_id}/")
        self.assertEqual(mismatched_parent_response.status_code, status.HTTP_404_NOT_FOUND)

        pending_content_response = self.client.get(f"{self.datasets_url}{dataset['id']}/exports/{export_id}/content/")
        self.assertEqual(pending_content_response.status_code, status.HTTP_409_CONFLICT)

        asset = ExportedAsset.objects.get(id=export_id)
        assert asset.export_context is not None
        self.assertEqual(asset.export_context["kind"], DATASET_EXPORT_KIND)
        asset.content = b'{"input":{"question":"First"}}\n'
        asset.save(update_fields=["content"])
        content_response = self.client.get(f"{self.datasets_url}{dataset['id']}/exports/{export_id}/content/")

        self.assertEqual(content_response.status_code, status.HTTP_200_OK)
        self.assertEqual(content_response.content, asset.content)
        self.assertIn("attachment", content_response["Content-Disposition"])

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.ai_observability.backend.api.datasets.DatasetExportRateThrottle.rate", new="1/day")
    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_dataset_export_throttles_session_authenticated_requests(
        self, _async_connect: AsyncMock, *_args: object
    ) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        dataset = self._create_dataset()
        self._create_item(dataset["id"])
        export_url = f"{self.datasets_url}{dataset['id']}/exports/"

        self.assertEqual(self.client.post(export_url, {}, format="json").status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.client.post(export_url, {}, format="json").status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @patch("products.ai_observability.backend.api.datasets.is_impersonated", return_value=True)
    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_dataset_export_logs_exported_asset_activity(
        self, _async_connect: AsyncMock, _is_impersonated: MagicMock
    ) -> None:
        dataset = self._create_dataset()
        item = self._create_item(dataset["id"])

        response = self.client.post(f"{self.datasets_url}{dataset['id']}/exports/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log = ActivityLog.objects.get(scope="ExportedAsset", item_id=str(response.data["id"]))
        assert log.detail is not None
        self.assertEqual(log.activity, "exported")
        self.assertEqual(log.team_id, self.team.id)
        self.assertEqual(log.user_id, self.user.id)
        self.assertTrue(log.was_impersonated)
        self.assertEqual(log.detail["name"], f"{dataset['name']}-r{item['dataset_revision']}")
        self.assertEqual(log.detail["type"], DATASET_EXPORT_KIND)
        self.assertEqual(log.detail["changes"][0]["after"], ExportedAsset.ExportFormat.JSONL)

    def test_dataset_export_rejects_unknown_request_fields(self) -> None:
        dataset = self._create_dataset()
        self._create_item(dataset["id"])

        response = self.client.post(
            f"{self.datasets_url}{dataset['id']}/exports/",
            {"revison": 1},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "This field is not supported.",
                "attr": "revison",
            },
        )

    @patch("products.exports.backend.facade.api.async_connect", new_callable=AsyncMock)
    def test_dataset_export_reports_a_stuck_workflow_as_failed(self, _async_connect: AsyncMock) -> None:
        dataset = self._create_dataset()
        self._create_item(dataset["id"])
        create_response = self.client.post(f"{self.datasets_url}{dataset['id']}/exports/", {}, format="json")
        export_id = create_response.data["id"]
        ExportedAsset.objects.filter(id=export_id).update(created_at=now() - timedelta(minutes=36))

        status_response = self.client.get(f"{self.datasets_url}{dataset['id']}/exports/{export_id}/")
        content_response = self.client.get(f"{self.datasets_url}{dataset['id']}/exports/{export_id}/content/")

        self.assertEqual(status_response.data["status"], "failed")
        self.assertEqual(status_response.data["exception"], DATASET_EXPORT_STUCK_MESSAGE)
        self.assertEqual(content_response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(content_response.data, {"detail": DATASET_EXPORT_STUCK_MESSAGE})

    def test_dataset_export_rejects_an_invalid_export_id(self) -> None:
        dataset = self._create_dataset()

        response = self.client.get(f"{self.datasets_url}{dataset['id']}/exports/{'9' * 5_000}/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
