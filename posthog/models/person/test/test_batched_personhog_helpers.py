from unittest.mock import ANY, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person.util import (
    _batched_get_distinct_ids_for_persons,
    _batched_get_persons_by_distinct_ids,
    _batched_get_persons_by_uuids,
    get_persons_mapped_by_distinct_id,
)
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.personhog_client.proto import ReadOptions
from posthog.personhog_client.proto.generated.personhog.types.v1 import person_pb2


class TestBatchedGetPersonsByUuids(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_batch", 500, 2, 1),
            ("multiple_batches", 2, 5, 3),
        ]
    )
    def test_returns_all_persons(self, _name, batch_size, n_persons, expected_calls):
        with patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", batch_size):
            with fake_personhog_client() as fake:
                for i in range(n_persons):
                    fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}"])

                result = _batched_get_persons_by_uuids(1, [f"uuid-{i}" for i in range(n_persons)], "test")

                assert len(result) == n_persons
                assert {p.uuid for p in result} == {f"uuid-{i}" for i in range(n_persons)}
                fake.assert_called("get_persons_by_uuids", times=expected_calls)

    def test_empty_input(self):
        with fake_personhog_client():
            result = _batched_get_persons_by_uuids(1, [], "test")

            assert result == []

    def test_filters_wrong_team(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])
            fake.add_person(team_id=999, person_id=2, uuid="uuid-2", distinct_ids=["d2"])

            result = _batched_get_persons_by_uuids(1, ["uuid-1", "uuid-2"], "test")

            assert len(result) == 1
            assert result[0].uuid == "uuid-1"

    def test_filters_persons_with_no_id(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=0, uuid="uuid-zero", distinct_ids=["d0"])
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

            result = _batched_get_persons_by_uuids(1, ["uuid-zero", "uuid-1"], "test")

            assert len(result) == 1
            assert result[0].uuid == "uuid-1"

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

        with (
            patch("posthog.models.person.util._get_client", return_value=mock_client),
            patch("posthog.models.person.util.PERSONHOG_TEAM_MISMATCH_TOTAL") as mock_metric,
        ):
            result = _batched_get_persons_by_uuids(1, ["uuid-0", "uuid-1", "uuid-2", "uuid-3"], "test_op")

        assert len(result) == 2
        assert mock_metric.labels.call_count == 2
        mock_metric.labels.assert_any_call(operation="test_op", client_name=ANY)

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_preserves_order_across_batches(self):
        with fake_personhog_client() as fake:
            for i in range(4):
                fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}"])

            result = _batched_get_persons_by_uuids(1, ["uuid-0", "uuid-1", "uuid-2", "uuid-3"], "test")

            assert [p.uuid for p in result] == ["uuid-0", "uuid-1", "uuid-2", "uuid-3"]

    def test_missing_uuids_excluded(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

            result = _batched_get_persons_by_uuids(1, ["uuid-1", "uuid-missing"], "test")

            assert len(result) == 1
            assert result[0].uuid == "uuid-1"


class TestBatchedGetPersonsByDistinctIds(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_batch", 500, 2, 1),
            ("multiple_batches", 2, 5, 3),
        ]
    )
    def test_returns_all_persons(self, _name, batch_size, n_persons, expected_calls):
        with patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", batch_size):
            with fake_personhog_client() as fake:
                for i in range(n_persons):
                    fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"did-{i}"])

                result = _batched_get_persons_by_distinct_ids(1, [f"did-{i}" for i in range(n_persons)], "test")

                assert len(result) == n_persons
                assert {r.distinct_id for r in result} == {f"did-{i}" for i in range(n_persons)}
                fake.assert_called("get_persons_by_distinct_ids_in_team", times=expected_calls)

    def test_empty_input(self):
        with fake_personhog_client():
            result = _batched_get_persons_by_distinct_ids(1, [], "test")

            assert result == []

    @parameterized.expand(
        [
            ("single_batch", 500, 2, 1),
            ("across_batches", 2, 3, 1),
        ]
    )
    def test_deduplicates_same_person(self, _name, batch_size, n_distinct_ids, expected_result_count):
        with patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", batch_size):
            with fake_personhog_client() as fake:
                dids = [f"did-{i}" for i in range(n_distinct_ids)]
                fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=dids)

                result = _batched_get_persons_by_distinct_ids(1, dids, "test")

                assert len(result) == expected_result_count
                assert result[0].person.id == 42

    @parameterized.expand(
        [
            ("single_batch", 500, 2),
            ("across_batches", 2, 3),
        ]
    )
    def test_no_dedup_returns_all_entries(self, _name, batch_size, n_distinct_ids):
        with patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", batch_size):
            with fake_personhog_client() as fake:
                dids = [f"did-{i}" for i in range(n_distinct_ids)]
                fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=dids)

                result = _batched_get_persons_by_distinct_ids(1, dids, "test", deduplicate_by_person=False)

                assert len(result) == n_distinct_ids
                assert {r.distinct_id for r in result} == set(dids)
                assert all(r.person.id == 42 for r in result)

    def test_filters_wrong_team(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["did-1"])
            fake.add_person(team_id=999, person_id=2, uuid="uuid-2", distinct_ids=["did-2"])

            result = _batched_get_persons_by_distinct_ids(1, ["did-1", "did-2"], "test")

            assert len(result) == 1
            assert result[0].person.uuid == "uuid-1"

    def test_missing_distinct_ids_excluded(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["did-1"])

            result = _batched_get_persons_by_distinct_ids(1, ["did-1", "did-missing"], "test")

            assert len(result) == 1

    def test_forwards_read_options_to_request(self):
        opts = ReadOptions(field_mask=["uuid", "id", "team_id"])
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["did-1"])

            _batched_get_persons_by_distinct_ids(1, ["did-1"], "test", read_options=opts)

            calls = fake.assert_called("get_persons_by_distinct_ids_in_team", times=1)
            assert list(calls[0].request.read_options.field_mask) == ["uuid", "id", "team_id"]

    def test_no_read_options_by_default(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["did-1"])

            _batched_get_persons_by_distinct_ids(1, ["did-1"], "test")

            calls = fake.assert_called("get_persons_by_distinct_ids_in_team", times=1)
            assert list(calls[0].request.read_options.field_mask) == []

    @patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", 2)
    def test_read_options_forwarded_to_all_batches(self):
        opts = ReadOptions(field_mask=["uuid"])
        with fake_personhog_client() as fake:
            for i in range(3):
                fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"did-{i}"])

            _batched_get_persons_by_distinct_ids(1, ["did-0", "did-1", "did-2"], "test", read_options=opts)

            calls = fake.assert_called("get_persons_by_distinct_ids_in_team", times=2)
            for call in calls:
                assert list(call.request.read_options.field_mask) == ["uuid"]


class TestBatchedGetDistinctIdsForPersons(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_batch", 500, 2, 1),
            ("multiple_batches", 2, 5, 3),
        ]
    )
    def test_returns_all_distinct_ids(self, _name, batch_size, n_persons, expected_calls):
        with patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", batch_size):
            with fake_personhog_client() as fake:
                for i in range(n_persons):
                    fake.add_person(team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}"])

                result = _batched_get_distinct_ids_for_persons(1, list(range(1, n_persons + 1)))

                assert len(result) == n_persons
                for i in range(n_persons):
                    assert result[i + 1] == [f"d{i}"]
                fake.assert_called("get_distinct_ids_for_persons", times=expected_calls)

    def test_empty_input(self):
        with fake_personhog_client():
            result = _batched_get_distinct_ids_for_persons(1, [])

            assert result == {}

    @parameterized.expand(
        [
            ("single_batch", 500, 1),
            ("across_batches", 2, 3),
        ]
    )
    def test_limit_per_person(self, _name, batch_size, n_persons):
        with patch("posthog.models.person.util.PERSONHOG_BATCH_SIZE", batch_size):
            with fake_personhog_client() as fake:
                for i in range(n_persons):
                    fake.add_person(
                        team_id=1, person_id=i + 1, uuid=f"uuid-{i}", distinct_ids=[f"d{i}a", f"d{i}b", f"d{i}c"]
                    )

                result = _batched_get_distinct_ids_for_persons(1, list(range(1, n_persons + 1)), limit_per_person=1)

                assert all(len(dids) == 1 for dids in result.values())

    def test_limit_per_person_none_returns_all(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1", "d2", "d3"])

            result = _batched_get_distinct_ids_for_persons(1, [1])

            assert len(result[1]) == 3

    def test_missing_person_gets_empty_list(self):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=1, uuid="uuid-1", distinct_ids=["d1"])

            result = _batched_get_distinct_ids_for_persons(1, [1, 999])

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
        with fake_personhog_client() as fake:
            fake.add_person(team_id=1, person_id=42, uuid="uuid-42", distinct_ids=["did-1", "did-2", "did-3"])

            results = _batched_get_persons_by_distinct_ids(
                1, ["did-1", "did-2", "did-3"], "test", deduplicate_by_person=False
            )

            assert len(results) == 3
            assert {r.distinct_id for r in results} == {"did-1", "did-2", "did-3"}
            assert all(r.person.id == 42 for r in results)
            fake.assert_called("get_persons_by_distinct_ids_in_team", times=2)
