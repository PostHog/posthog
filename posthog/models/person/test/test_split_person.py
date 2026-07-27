from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import Person
from posthog.models.person.missing_person import uuidFromDistinctId
from posthog.models.person.util import get_person_by_distinct_id, get_person_by_id
from posthog.personhog_client.fake_client import FakePersonHogClient, fake_personhog_client
from posthog.test.persons import add_distinct_id, create_person


@patch("posthog.models.person.util.create_person")
@patch("posthog.models.person.util.create_person_distinct_id")
class TestSplitPerson(BaseTest):
    """split_person reads and writes person data exclusively through personhog.

    The local DB person row only matters for the legacy properties-wipe path;
    PDI rows are created here purely to prove the split never touches them
    via the ORM.
    """

    def _setup_person(
        self,
        fake: FakePersonHogClient,
        distinct_ids: list[str],
        mock_create_pdi,
        mock_create_person,
        properties: dict | None = None,
        version: int = 0,
    ) -> Person:
        person = create_person(
            team=self.team,
            properties=properties or {},
            version=version,
        )
        for distinct_id in distinct_ids:
            add_distinct_id(person=person, distinct_id=distinct_id)
        fake.add_person(
            team_id=self.team.id,
            person_id=person.id,
            uuid=str(person.uuid),
            distinct_ids=distinct_ids,
            version=version,
        )
        # Reset mocks after setup so post_save signal calls from setup don't count
        mock_create_pdi.reset_mock()
        mock_create_person.reset_mock()
        return person

    def test_split_with_main_distinct_id(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(
                fake,
                ["id1", "id2", "id3"],
                mock_create_pdi,
                mock_create_person,
                properties={"email": "test@example.com", "name": "Test"},
            )

            person.split_person(main_distinct_id="id1")

            split_calls = fake.assert_called("split_person", times=1)
            assert set(split_calls[0].request.distinct_ids_to_split) == {"id2", "id3"}
            assert split_calls[0].request.team_id == self.team.id
            assert split_calls[0].request.person_id == person.id

            # The fake's state reflects the move: id1 stays, id2/id3 land on distinct new persons
            assert fake._persons_by_distinct_id[(self.team.id, "id1")].id == person.id
            moved_2 = fake._persons_by_distinct_id[(self.team.id, "id2")]
            moved_3 = fake._persons_by_distinct_id[(self.team.id, "id3")]
            assert moved_2.id != person.id
            assert moved_3.id != person.id
            assert moved_2.id != moved_3.id

        # Original person keeps its properties when main_distinct_id is provided
        assert person.properties == {"email": "test@example.com", "name": "Test"}

        assert mock_create_pdi.call_count == 2
        assert mock_create_person.call_count == 2

    def test_split_does_not_write_orm(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2", "id3"], mock_create_pdi, mock_create_person)

            person.split_person(main_distinct_id="id1")

            # The write went through the RPC — reads resolve via personhog, not the ORM.
            # "id1" stays on the original person; "id2"/"id3" each moved to a new person.
            assert get_person_by_distinct_id(self.team.id, "id1").pk == person.id  # type: ignore[union-attr]
            assert get_person_by_distinct_id(self.team.id, "id2").pk != person.id  # type: ignore[union-attr]
            assert get_person_by_distinct_id(self.team.id, "id3").pk != person.id  # type: ignore[union-attr]
            assert get_person_by_id(self.team.id, person.id) is not None

    def test_split_without_main_distinct_id_keeps_properties(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(
                fake,
                ["id1", "id2"],
                mock_create_pdi,
                mock_create_person,
                properties={"email": "test@example.com"},
            )

            person.split_person(main_distinct_id=None)

            # First distinct_id from the fetch becomes the main; only the rest are split
            split_calls = fake.assert_called("split_person", times=1)
            split_ids = set(split_calls[0].request.distinct_ids_to_split)
            assert len(split_ids) == 1
            assert split_ids == {"id2"}

        assert person.properties == {"email": "test@example.com"}

    def test_split_with_max_splits(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2", "id3", "id4"], mock_create_pdi, mock_create_person)

            person.split_person(main_distinct_id="id1", max_splits=2)

            split_calls = fake.assert_called("split_person", times=1)
            assert len(split_calls[0].request.distinct_ids_to_split) == 2
            assert "id1" not in split_calls[0].request.distinct_ids_to_split

    def test_split_single_distinct_id_is_noop(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["only_id"], mock_create_pdi, mock_create_person)

            person.split_person(main_distinct_id="only_id")

            fake.assert_not_called("split_person")
        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_split_publishes_versions_from_rpc(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2"], mock_create_pdi, mock_create_person, version=5)

            person.split_person(main_distinct_id="id1")

        assert mock_create_person.call_count == 1
        assert mock_create_person.call_args.kwargs["version"] == 5 + 101
        assert mock_create_pdi.call_count == 1
        assert mock_create_pdi.call_args.kwargs["version"] == 101  # PDI version 0 + 101

    def test_split_publishes_deterministic_uuids(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2"], mock_create_pdi, mock_create_person)

            person.split_person(main_distinct_id="id1")

        expected_uuid = str(uuidFromDistinctId(self.team.id, "id2"))
        assert mock_create_person.call_args.kwargs["uuid"] == expected_uuid
        assert mock_create_pdi.call_args.kwargs["person_id"] == expected_uuid

    def test_split_publishes_correct_kafka_messages(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2", "id3"], mock_create_pdi, mock_create_person)

            person.split_person(main_distinct_id="id1")

        assert mock_create_pdi.call_count == 2
        assert mock_create_person.call_count == 2

        kafka_pdi_distinct_ids = {call.kwargs["distinct_id"] for call in mock_create_pdi.call_args_list}
        assert kafka_pdi_distinct_ids == {"id2", "id3"}

        for call in mock_create_pdi.call_args_list:
            assert call.kwargs["team_id"] == self.team.id
            assert call.kwargs["is_deleted"] is False

        for call in mock_create_person.call_args_list:
            assert call.kwargs["team_id"] == self.team.id

    def test_split_pre_existing_person_keeps_created_at_and_bumps_version(self, mock_create_pdi, mock_create_person):
        # A pre-existing split target (e.g. from a previous partial run) keeps
        # its original created_at but gets the new version; the Kafka message
        # must carry both so ClickHouse converges on the Postgres state.
        original_created_at = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)

        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2"], mock_create_pdi, mock_create_person, version=5)
            pre_existing_uuid = str(uuidFromDistinctId(self.team.id, "id2"))
            fake.add_person(
                team_id=self.team.id,
                person_id=999_999,
                uuid=pre_existing_uuid,
                created_at=int(original_created_at.timestamp() * 1000),
            )

            person.split_person(main_distinct_id="id1")

            assert fake._persons_by_uuid[(self.team.id, pre_existing_uuid)].version == 5 + 101

        assert mock_create_person.call_count == 1
        assert mock_create_person.call_args.kwargs["uuid"] == pre_existing_uuid
        assert mock_create_person.call_args.kwargs["version"] == 5 + 101
        assert mock_create_person.call_args.kwargs["created_at"] == original_created_at

    def test_partial_split_moves_only_specified_distinct_ids(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(
                fake,
                ["keep1", "move1", "keep2", "move2", "keep3"],
                mock_create_pdi,
                mock_create_person,
                properties={"email": "mega@example.com", "name": "Mega"},
            )

            person.split_person(main_distinct_id=None, distinct_ids_to_split=["move1", "move2"])

            split_calls = fake.assert_called("split_person", times=1)
            assert list(split_calls[0].request.distinct_ids_to_split) == ["move1", "move2"]

            for did in ["keep1", "keep2", "keep3"]:
                assert fake._persons_by_distinct_id[(self.team.id, did)].id == person.id
            assert fake._persons_by_distinct_id[(self.team.id, "move1")].id != person.id
            assert fake._persons_by_distinct_id[(self.team.id, "move2")].id != person.id

        # Original person keeps its properties intact — this is the key partial-split guarantee.
        assert person.properties == {"email": "mega@example.com", "name": "Mega"}

        assert mock_create_pdi.call_count == 2
        assert mock_create_person.call_count == 2

    def test_partial_split_rejects_unknown_distinct_id(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2"], mock_create_pdi, mock_create_person)

            with self.assertRaises(KeyError):
                person.split_person(main_distinct_id=None, distinct_ids_to_split=["id1", "not_on_this_person"])

        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_partial_split_ignores_main_distinct_id_and_max_splits(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["a", "b", "c", "d"], mock_create_pdi, mock_create_person)

            # main_distinct_id and max_splits should both be ignored when the explicit list is given.
            person.split_person(main_distinct_id="a", max_splits=1, distinct_ids_to_split=["b", "c"])

            split_calls = fake.assert_called("split_person", times=1)
            assert list(split_calls[0].request.distinct_ids_to_split) == ["b", "c"]

    def test_partial_split_empty_list_is_noop(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2"], mock_create_pdi, mock_create_person)

            person.split_person(main_distinct_id=None, distinct_ids_to_split=[])

            fake.assert_not_called("split_person")
        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_partial_split_dedupes_duplicates(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2"], mock_create_pdi, mock_create_person)

            person.split_person(main_distinct_id=None, distinct_ids_to_split=["id2", "id2"])

            split_calls = fake.assert_called("split_person", times=1)
            assert list(split_calls[0].request.distinct_ids_to_split) == ["id2"]
        assert mock_create_pdi.call_count == 1
        assert mock_create_person.call_count == 1

    def test_split_paginates_fetch_and_splits(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["main", "a", "b", "c", "d", "e"], mock_create_pdi, mock_create_person)

            with patch("posthog.models.person.person.PERSONHOG_SPLIT_BATCH_SIZE", 2):
                person.split_person(main_distinct_id="main")

            # Each page fetches limit=3 (batch_size+1), splits up to 2 non-main IDs,
            # then the next fetch returns a smaller set because the split IDs are gone.
            split_calls = fake.assert_called("split_person")
            total_split = sum(len(call.request.distinct_ids_to_split) for call in split_calls)
            assert total_split == 5

            # All fetch calls used the limit
            fetch_calls = [c for c in fake.calls if c.method == "get_distinct_ids_for_person"]
            for call in fetch_calls:
                assert call.request.limit == 3  # PERSONHOG_SPLIT_BATCH_SIZE + 1

        assert mock_create_person.call_count == 5
        assert mock_create_pdi.call_count == 5

    def test_split_raises_when_rpc_fails(self, mock_create_pdi, mock_create_person):
        # No ORM fallback: an RPC failure propagates and nothing is published.
        with fake_personhog_client() as fake:
            person = self._setup_person(fake, ["id1", "id2"], mock_create_pdi, mock_create_person)

            def failing_split(request, timeout=None):
                raise RuntimeError("simulated gRPC failure")

            fake.split_person = failing_split

            with self.assertRaises(RuntimeError):
                person.split_person(main_distinct_id="id1")

            # The split never happened — "id2" still resolves to the original person — and no Kafka was published
            assert get_person_by_distinct_id(self.team.id, "id2").pk == person.id  # type: ignore[union-attr]
        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_split_from_stub_person_keeps_properties(self, mock_create_pdi, mock_create_person):
        """Verify split works when called on a stub Person(pk=..., team_id=...)
        rather than a DB-fetched instance — this is how the Celery task invokes it."""
        with fake_personhog_client() as fake:
            person = self._setup_person(
                fake,
                ["id1", "id2"],
                mock_create_pdi,
                mock_create_person,
                properties={"email": "test@example.com"},
            )

            stub = Person(pk=person.id, team_id=self.team.id)
            stub.split_person(main_distinct_id=None)

            split_calls = fake.assert_called("split_person", times=1)
            assert list(split_calls[0].request.distinct_ids_to_split) == ["id2"]

        assert person.properties == {"email": "test@example.com"}

    def test_split_person_not_found_in_personhog(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client():
            stub = Person(pk=999_999, team_id=self.team.id)
            with self.assertRaises(ValueError, msg="Person not found"):
                stub.split_person(main_distinct_id="anything")

        mock_create_pdi.assert_not_called()
        mock_create_person.assert_not_called()

    def test_max_splits_caps_across_pages(self, mock_create_pdi, mock_create_person):
        with fake_personhog_client() as fake:
            ids = ["main"] + [f"id_{i}" for i in range(10)]
            person = self._setup_person(fake, ids, mock_create_pdi, mock_create_person)

            with patch("posthog.models.person.person.PERSONHOG_SPLIT_BATCH_SIZE", 3):
                person.split_person(main_distinct_id="main", max_splits=5)

            split_calls = fake.assert_called("split_person")
            total_split = sum(len(call.request.distinct_ids_to_split) for call in split_calls)
            assert total_split == 5

        assert mock_create_person.call_count == 5
        assert mock_create_pdi.call_count == 5
