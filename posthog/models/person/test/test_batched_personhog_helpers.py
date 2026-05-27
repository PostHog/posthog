from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.models.person.util import (
    _batched_get_distinct_ids_for_persons,
    _batched_get_persons_by_distinct_ids,
    _batched_get_persons_by_uuids,
    get_persons_mapped_by_distinct_id,
)
from posthog.personhog_client.fake_client import FakePersonHogClient, fake_personhog_client
from posthog.personhog_client.proto.generated.personhog.types.v1 import person_pb2


class TestBatchedGetPersonsByUuids(SimpleTestCase):
    def test_single_batch(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
        fake.add_person(team_id=1, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

        result = _batched_get_persons_by_uuids(fake, 1, ["uuid-1", "uuid-2"], "test")

        assert len(result) == 2
        assert {p.uuid for p in result} == {"uuid-1", "uuid-2"}
        fake.assert_called("get_persons_by_uuids", times=1)

    def test_empty_input(self):
        fake = FakePersonHogClient()

        result = _batched_get_persons_by_uuids(fake, 1, [], "test")

        assert result == []
        fake.assert_not_called("get_persons_by_uuids")

    def test_filters_wrong_team(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
        fake.add_person(team_id=999, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

        result = _batched_get_persons_by_uuids(fake, 1, ["uuid-1", "uuid-2"], "test")

        assert len(result) == 1
        assert result[0].uuid == "uuid-1"

    def test_filters_persons_with_no_id(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=0, uuid="uuid-zero", distinct_ids=["d0"])
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

        result = _batched_get_persons_by_uuids(fake, 1, ["uuid-zero", "uuid-1"], "test")

        assert len(result) == 1
        assert result[0].uuid == "uuid-1"

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_multiple_batches(self):
        fake = FakePersonHogClient()
        for i in range(5):
            fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}"])

        result = _batched_get_persons_by_uuids(fake, 1, [f"uuid-{i}" for i in range(5)], "test")

        assert len(result) == 5
        assert {p.uuid for p in result} == {f"uuid-{i}" for i in range(5)}
        fake.assert_called("get_persons_by_uuids", times=3)

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_team_mismatch_metric_across_batches(self):
        wrong_team_person = person_pb2.Person(id=2, uuid="uuid-1", team_id=999)
        right_team_person_1 = person_pb2.Person(id=1, uuid="uuid-0", team_id=1)
        right_team_person_2 = person_pb2.Person(id=3, uuid="uuid-2", team_id=1)
        wrong_team_person_2 = person_pb2.Person(id=4, uuid="uuid-3", team_id=888)

        mock_client = MagicMock()
        mock_client.get_persons_by_uuids.side_effect = [
            person_pb2.PersonsResponse(persons=[right_team_person_1, wrong_team_person]),
            person_pb2.PersonsResponse(persons=[right_team_person_2, wrong_team_person_2]),
        ]

        with patch("posthog.models.person.util.PERSONHOG_TEAM_MISMATCH_TOTAL") as mock_metric:
            result = _batched_get_persons_by_uuids(mock_client, 1, ["uuid-0", "uuid-1", "uuid-2", "uuid-3"], "test_op")

        assert len(result) == 2
        assert mock_metric.labels.call_count == 2
        mock_metric.labels.assert_any_call(operation="test_op", client_name="posthog-django")

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_preserves_order_across_batches(self):
        fake = FakePersonHogClient()
        for i in range(4):
            fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}"])

        result = _batched_get_persons_by_uuids(fake, 1, ["uuid-0", "uuid-1", "uuid-2", "uuid-3"], "test")

        assert [p.uuid for p in result] == ["uuid-0", "uuid-1", "uuid-2", "uuid-3"]

    def test_missing_uuids_excluded(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

        result = _batched_get_persons_by_uuids(fake, 1, ["uuid-1", "uuid-missing"], "test")

        assert len(result) == 1
        assert result[0].uuid == "uuid-1"


class TestBatchedGetPersonsByDistinctIds(SimpleTestCase):
    def test_single_batch(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["did-1"])
        fake.add_person(team_id=1, person_id=2, uuid="uuid-2", distinct_ids=["did-2"])

        result = _batched_get_persons_by_distinct_ids(fake, 1, ["did-1", "did-2"], "test")

        assert len(result) == 2
        assert {r.distinct_id for r in result} == {"did-1", "did-2"}
        fake.assert_called("get_persons_by_distinct_ids_in_team", times=1)

    def test_empty_input(self):
        fake = FakePersonHogClient()

        result = _batched_get_persons_by_distinct_ids(fake, 1, [], "test")

        assert result == []
        fake.assert_not_called("get_persons_by_distinct_ids_in_team")

    def test_deduplicates_same_person_across_distinct_ids(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=["did-1", "did-2"])

        result = _batched_get_persons_by_distinct_ids(fake, 1, ["did-1", "did-2"], "test")

        assert len(result) == 1
        assert result[0].person.id == 42

    def test_no_dedup_returns_all_entries(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=["did-1", "did-2"])

        result = _batched_get_persons_by_distinct_ids(fake, 1, ["did-1", "did-2"], "test", deduplicate_by_person=False)

        assert len(result) == 2
        assert {r.distinct_id for r in result} == {"did-1", "did-2"}
        assert all(r.person.id == 42 for r in result)

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_deduplicates_across_batches(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=["did-1", "did-2", "did-3"])

        result = _batched_get_persons_by_distinct_ids(fake, 1, ["did-1", "did-2", "did-3"], "test")

        assert len(result) == 1
        assert result[0].person.id == 42
        fake.assert_called("get_persons_by_distinct_ids_in_team", times=2)

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_no_dedup_across_batches(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=["did-1", "did-2", "did-3"])

        result = _batched_get_persons_by_distinct_ids(
            fake, 1, ["did-1", "did-2", "did-3"], "test", deduplicate_by_person=False
        )

        assert len(result) == 3
        assert {r.distinct_id for r in result} == {"did-1", "did-2", "did-3"}

    def test_filters_wrong_team(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["did-1"])
        fake.add_person(team_id=999, person_id=2, uuid="uuid-2", distinct_ids=["did-2"])

        result = _batched_get_persons_by_distinct_ids(fake, 1, ["did-1", "did-2"], "test")

        assert len(result) == 1
        assert result[0].person.uuid == "uuid-1"

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_multiple_batches_multiple_persons(self):
        fake = FakePersonHogClient()
        for i in range(5):
            fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"did-{i}"])

        result = _batched_get_persons_by_distinct_ids(fake, 1, [f"did-{i}" for i in range(5)], "test")

        assert len(result) == 5
        fake.assert_called("get_persons_by_distinct_ids_in_team", times=3)

    def test_missing_distinct_ids_excluded(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["did-1"])

        result = _batched_get_persons_by_distinct_ids(fake, 1, ["did-1", "did-missing"], "test")

        assert len(result) == 1


class TestBatchedGetDistinctIdsForPersons(SimpleTestCase):
    def test_single_batch(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1a", "d1b"])
        fake.add_person(team_id=1, person_id=2, uuid="uuid-2", distinct_ids=["d2a"])

        result = _batched_get_distinct_ids_for_persons(fake, 1, [1, 2])

        assert result == {1: ["d1a", "d1b"], 2: ["d2a"]}
        fake.assert_called("get_distinct_ids_for_persons", times=1)

    def test_empty_input(self):
        fake = FakePersonHogClient()

        result = _batched_get_distinct_ids_for_persons(fake, 1, [])

        assert result == {}
        fake.assert_not_called("get_distinct_ids_for_persons")

    def test_limit_per_person(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1", "d2", "d3"])

        result = _batched_get_distinct_ids_for_persons(fake, 1, [1], limit_per_person=2)

        assert len(result[1]) == 2

    def test_limit_per_person_none_returns_all(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1", "d2", "d3"])

        result = _batched_get_distinct_ids_for_persons(fake, 1, [1])

        assert len(result[1]) == 3

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_multiple_batches(self):
        fake = FakePersonHogClient()
        for i in range(5):
            fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}"])

        result = _batched_get_distinct_ids_for_persons(fake, 1, [1, 2, 3, 4, 5])

        assert len(result) == 5
        for i in range(5):
            assert result[i + 1] == [f"d{i}"]
        fake.assert_called("get_distinct_ids_for_persons", times=3)

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_limit_per_person_applied_to_each_batch(self):
        fake = FakePersonHogClient()
        for i in range(3):
            fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}a", f"d{i}b", f"d{i}c"])

        result = _batched_get_distinct_ids_for_persons(fake, 1, [1, 2, 3], limit_per_person=1)

        assert all(len(dids) == 1 for dids in result.values())

    def test_missing_person_gets_empty_list(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

        result = _batched_get_distinct_ids_for_persons(fake, 1, [1, 999])

        assert result[1] == ["d1"]
        assert result[999] == []


class TestGetPersonsMappedByDistinctIdDedup(SimpleTestCase):
    def test_multiple_distinct_ids_same_person_all_present(self):
        with fake_personhog_client() as fake:
            fake.add_person(
                team_id=1, person_id=42, uuid="550e8400-e29b-41d4-a716-446655440042", distinct_ids=["did-1", "did-2"]
            )

            result = get_persons_mapped_by_distinct_id(1, ["did-1", "did-2"])

            assert len(result) == 2
            assert "did-1" in result
            assert "did-2" in result
            assert result["did-1"].id == 42
            assert result["did-2"].id == 42
            assert result["did-1"].distinct_ids == ["did-1"]
            assert result["did-2"].distinct_ids == ["did-2"]

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_multiple_distinct_ids_same_person_across_batches(self):
        fake = FakePersonHogClient()
        fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=["did-1", "did-2", "did-3"])

        results = _batched_get_persons_by_distinct_ids(
            fake, 1, ["did-1", "did-2", "did-3"], "test", deduplicate_by_person=False
        )

        assert len(results) == 3
        assert {r.distinct_id for r in results} == {"did-1", "did-2", "did-3"}
        assert all(r.person.id == 42 for r in results)
        fake.assert_called("get_persons_by_distinct_ids_in_team", times=2)
