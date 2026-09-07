import json

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.utils import uuid7

from products.cohorts.backend.population import input_store
from products.cohorts.backend.population.test.storage_fake import fake_population_storage


@pytest.fixture
def storage():
    with fake_population_storage() as fake:
        yield fake


class TestCohortPopulationInputStore:
    @parameterized.expand(
        [
            ("blank_and_whitespace", "distinct_id", ["a", "  ", "", " b "], ["a", "b"]),
            ("keeps_first_seen_order", "distinct_id", ["c", "a", "c", "b", "a"], ["c", "a", "b"]),
            ("emails_fold_case", "email", ["A@example.com", "a@EXAMPLE.com"], ["a@example.com"]),
            (
                "uuids_are_canonical",
                "person_id",
                ["000000000000000000000000000000AB", "00000000-0000-0000-0000-0000000000ab"],
                ["00000000-0000-0000-0000-0000000000ab"],
            ),
        ]
    )
    def test_normalization(self, _name: str, id_type: str, raw: list[str], expected: list[str]) -> None:
        assert input_store.normalize_identifiers(raw, id_type) == expected

    def test_an_unsupported_id_type_is_rejected_before_anything_is_written(self, storage) -> None:
        with pytest.raises(ValueError):
            input_store.write_input(team_id=1, operation_id=uuid7(), identifiers=["a"], id_type="phone")

        assert storage.objects == {}

    def test_unavailable_storage_cannot_silently_accept_input(self) -> None:
        from posthog.storage.object_storage import ObjectStorageError, UnavailableStorage

        with patch.object(input_store.object_storage, "object_storage_client", return_value=UnavailableStorage()):
            with pytest.raises(ObjectStorageError):
                input_store.write_input(team_id=7, operation_id=uuid7(), identifiers=["a"], id_type="distinct_id")

    def test_cleanup_includes_uncheckpointed_pages_and_retries_partial_deletion(self, storage) -> None:
        manifest = input_store.empty_manifest(team_id=7, operation_id=uuid7(), id_type="distinct_id")
        input_store.append_chunk(manifest, ["uncheckpointed"])
        other = input_store.write_input(team_id=7, operation_id=uuid7(), identifiers=["keep"], id_type="distinct_id")
        with patch.object(storage, "delete_objects", return_value=["failed"]):
            with pytest.raises(input_store.ObjectStorageError):
                input_store.delete_input(manifest)
        input_store.delete_input(manifest)
        assert len(storage.objects) == 1
        assert input_store.read_chunk(other, 0) == ["keep"]

    def test_identifiers_are_written_in_bounded_chunks_and_read_back_intact(self, storage) -> None:
        identifiers = [f"id-{index}" for index in range(2500)]

        manifest = input_store.write_input(
            team_id=7, operation_id=uuid7(), identifiers=identifiers, id_type="distinct_id", chunk_size=1000
        )

        assert manifest["chunks"] == 3
        assert manifest["total"] == 2500
        read_back = [
            identifier for index in range(manifest["chunks"]) for identifier in input_store.read_chunk(manifest, index)
        ]
        assert read_back == identifiers
        assert len(input_store.read_chunk(manifest, 2)) == 500

    def test_an_empty_upload_writes_no_chunks_and_reports_none_to_write(self, storage) -> None:
        manifest = input_store.write_input(team_id=7, operation_id=uuid7(), identifiers=[], id_type="person_id")

        assert manifest == {
            "schema": input_store.MANIFEST_SCHEMA,
            "prefix": manifest["prefix"],
            "chunks": 0,
            "total": 0,
            "id_type": "person_id",
        }
        assert storage.objects == {}

    def test_a_chunk_that_left_storage_raises_rather_than_reading_as_empty(self, storage) -> None:
        manifest = input_store.write_input(
            team_id=7, operation_id=uuid7(), identifiers=["a", "b"], id_type="distinct_id"
        )
        storage.objects.clear()

        with pytest.raises(input_store.CohortPopulationInputMissing):
            input_store.read_chunk(manifest, 0)

    def test_reading_past_the_manifest_raises_rather_than_reading_another_run(self, storage) -> None:
        manifest = input_store.write_input(team_id=7, operation_id=uuid7(), identifiers=["a"], id_type="distinct_id")

        with pytest.raises(input_store.CohortPopulationInputMissing):
            input_store.read_chunk(manifest, 1)

    def test_appending_a_page_grows_the_manifest_without_rewriting_earlier_chunks(self, storage) -> None:
        manifest = input_store.empty_manifest(team_id=7, operation_id=uuid7(), id_type="distinct_id")

        manifest = input_store.append_chunk(manifest, ["a", "b"])
        first_chunk_key = next(iter(storage.objects))
        manifest = input_store.append_chunk(manifest, ["c"])

        assert manifest["chunks"] == 2
        assert manifest["total"] == 3
        assert json.loads(storage.objects[first_chunk_key]) == ["a", "b"]
        assert input_store.read_chunk(manifest, 1) == ["c"]

    def test_input_is_readable_only_while_the_chunks_are_actually_there(self, storage) -> None:
        manifest = input_store.write_input(team_id=7, operation_id=uuid7(), identifiers=["a"], id_type="distinct_id")
        assert input_store.input_is_readable(manifest) is True

        input_store.delete_input(manifest)

        assert input_store.input_is_readable(manifest) is False
        assert storage.objects == {}
