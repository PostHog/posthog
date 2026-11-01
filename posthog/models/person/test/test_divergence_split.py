import shlex
from io import StringIO
from pathlib import Path
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.utils.timezone import now

from confluent_kafka import KafkaError
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_DISTINCT_ID
from posthog.models.person import Person
from posthog.models.person.divergence import observe
from posthog.models.person.divergence.detach import SplitError, split_distinct_ids
from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2
from posthog.models.person.util import (
    DistinctIdForPerson,
    _batched_get_distinct_ids_for_persons,
    create_person as create_person_in_ch,
    get_distinct_id_rows,
    get_persons_by_uuids,
)
from posthog.models.signals import mute_selected_signals
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.test.persons import create_person

PERSON_UUID = "00000000-0000-0000-0000-0000000000a1"


def _insert_ch_mapping(team_id: int, distinct_id: str, person_uuid: str) -> None:
    sync_execute(
        BULK_INSERT_PERSON_DISTINCT_ID2,
        [
            {
                "distinct_id": distinct_id,
                "person_id": person_uuid,
                "team_id": team_id,
                "is_deleted": 0,
                "version": 0,
                "_timestamp": now().replace(tzinfo=None),
                "_offset": 0,
                "_partition": 0,
            }
        ],
        flush=False,
    )


def _failed_produce() -> ProduceResult:
    failed = ProduceResult(topic=KAFKA_PERSON)
    failed.set_result(KafkaError(-192, "Local: Message timed out"), None)
    return failed


@patch("posthog.models.person.util.create_person")
@patch("posthog.models.person.util.create_person_distinct_id")
class TestSplitDistinctIds(BaseTest):
    @parameterized.expand(
        [
            ("applies", ["id2", "id3"], True, ["id2", "id3"]),
            ("dry_run_writes_nothing", ["id2"], False, []),
            ("a_mistyped_id_stops_the_whole_split", ["id2", "typo"], True, SplitError),
            ("an_id_of_another_person_stops_the_whole_split", ["id2", "other-1"], True, SplitError),
            ("a_split_leaving_no_id_is_refused", ["id1", "id2", "id3"], True, SplitError),
            ("a_dry_run_leaving_no_id_is_refused", ["id1", "id2", "id3"], False, SplitError),
        ]
    )
    def test_split_moves_only_ids_live_on_the_person(
        self, _mock_create_pdi, _mock_create_person, _name, distinct_ids, apply, expected
    ):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.id, person_id=501, uuid=PERSON_UUID, distinct_ids=["id1", "id2", "id3"])
            fake.add_person(
                team_id=self.team.id,
                person_id=502,
                uuid="00000000-0000-0000-0000-0000000000a2",
                distinct_ids=["other-1"],
            )

            if expected is SplitError:
                with self.assertRaises(SplitError):
                    split_distinct_ids(self.team.id, PERSON_UUID, distinct_ids, apply=apply, log=lambda _: None)
                fake.assert_not_called("split_person")
                return

            assert (
                split_distinct_ids(self.team.id, PERSON_UUID, distinct_ids, apply=apply, log=lambda _: None) == expected
            )
            if apply:
                assert set(fake.assert_called("split_person", times=1)[0].request.distinct_ids_to_split) == set(
                    expected
                )
            else:
                fake.assert_not_called("split_person")
            owners = {d: fake._persons_by_distinct_id[(self.team.id, d)].id for d in ["id1", "id2", "id3"]}
            assert owners["id1"] == 501
            assert all((owners[d] != 501) == (d in expected) for d in ["id2", "id3"])

    def test_split_accepts_any_uuid_spelling_and_moves_each_id_once(self, *_mocks):
        with fake_personhog_client() as fake:
            fake.add_person(team_id=self.team.id, person_id=501, uuid=PERSON_UUID, distinct_ids=["id1", "id2"])

            moved = split_distinct_ids(
                self.team.id, PERSON_UUID.upper(), ["id2", "id2"], apply=True, log=lambda _: None
            )

            assert moved == ["id2"]
            assert list(fake.assert_called("split_person", times=1)[0].request.distinct_ids_to_split) == ["id2"]

    def test_a_split_that_moves_fewer_ids_than_asked_says_so(self, *_mocks):
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.person.Person._split_distinct_ids_batch", return_value=[]),
        ):
            fake.add_person(team_id=self.team.id, person_id=501, uuid=PERSON_UUID, distinct_ids=["id1", "id2"])

            with self.assertRaisesRegex(SplitError, "moved 0 of 1 distinct ids"):
                split_distinct_ids(self.team.id, PERSON_UUID, ["id2"], apply=True, log=lambda _: None)

    def test_a_failed_split_still_waits_for_the_messages_it_already_sent(self, *_mocks):
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.person.Person.split_person", side_effect=RuntimeError("batch 2 failed")),
            patch("posthog.models.person.divergence.detach.flush_all_producers", return_value=0) as flush,
        ):
            fake.add_person(team_id=self.team.id, person_id=501, uuid=PERSON_UUID, distinct_ids=["id1", "id2"])

            with self.assertRaisesRegex(SplitError, "batch 2 failed"):
                split_distinct_ids(self.team.id, PERSON_UUID, ["id2"], apply=True, log=lambda _: None)

            flush.assert_called_once()


class TestSplitLostInClickHouse(ClickhouseTestMixin, BaseTest):
    DISTINCT_IDS = ["id1", "id2", "id3", " padded id ", " ", "carriage\rreturn", "two\nlines"]

    def setUp(self) -> None:
        super().setUp()
        with mute_selected_signals():
            self.person = create_person(team=self.team, distinct_ids=self.DISTINCT_IDS)
        create_person_in_ch(team_id=self.team.pk, uuid=str(self.person.uuid), version=0, timestamp=now())
        for distinct_id in self.DISTINCT_IDS:
            _insert_ch_mapping(self.team.pk, distinct_id, str(self.person.uuid))
        sleep = patch("posthog.models.person.divergence.detach._sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def _split_losing_its_messages(self, distinct_ids: list[str]) -> list[str]:
        # The split's own publishes never reach Kafka, so Kafka has nothing queued to report undelivered.
        with (
            patch("posthog.models.person.util.create_person"),
            patch("posthog.models.person.util.create_person_distinct_id"),
        ):
            return split_distinct_ids(self.team.pk, str(self.person.uuid), distinct_ids, apply=True, log=lambda _: None)

    def _assert_clickhouse_agrees_with_postgres(self, distinct_id: str) -> None:
        owner = get_distinct_id_rows(self.team.pk, [distinct_id], strong=True)[0].person_uuid
        assert owner != str(self.person.uuid)
        assert observe.ch_mapping_states(self.team.pk, [distinct_id])[distinct_id].winner_person_uuid == owner
        assert observe.ch_person_states(self.team.pk, [owner])[owner].live_max_version is not None

    def _assert_clickhouse_shows_old_owner(self, distinct_id: str) -> None:
        winner = observe.ch_mapping_states(self.team.pk, [distinct_id])[distinct_id].winner_person_uuid
        assert winner == str(self.person.uuid)

    def test_a_split_clickhouse_missed_is_sent_again_so_no_scan_suggests_merging_it_back(self) -> None:
        assert self._split_losing_its_messages(["id2"]) == ["id2"]

        self._assert_clickhouse_agrees_with_postgres("id2")
        self._assert_clickhouse_shows_old_owner("id1")
        self.sleep.assert_not_called()

    def test_a_replica_behind_the_split_is_read_again_before_the_split_reports_it(self) -> None:
        reads: list[list[str]] = []

        def lagging_replica(team_id: int, person_uuids: list[str], **kwargs: Any) -> list[Person]:
            reads.append(person_uuids)
            return [] if len(reads) == 1 else get_persons_by_uuids(team_id, person_uuids, **kwargs)

        with patch("posthog.models.person.divergence.repair_plan.get_persons_by_uuids", side_effect=lagging_replica):
            assert self._split_losing_its_messages(["id2"]) == ["id2"]

        self.sleep.assert_called_once()
        self._assert_clickhouse_agrees_with_postgres("id2")

    def _split_failing_partway(self) -> None:
        with (
            patch("posthog.models.person.person.PERSONHOG_SPLIT_BATCH_SIZE", 1),
            patch(
                "posthog.models.person.person.Person._publish_split_to_kafka",
                side_effect=[None, RuntimeError("Kafka is down")],
            ),
        ):
            split_distinct_ids(self.team.pk, str(self.person.uuid), ["id2", "id3"], apply=True, log=lambda _: None)

    def test_a_split_that_fails_partway_sends_what_it_moved(self) -> None:
        with self.assertRaisesRegex(SplitError, "moved 2 of 2 distinct ids .* then failed: Kafka is down"):
            self._split_failing_partway()

        self._assert_clickhouse_agrees_with_postgres("id2")
        self._assert_clickhouse_agrees_with_postgres("id3")

    def test_a_split_that_fails_partway_and_cannot_be_sent_again_reports_both(self) -> None:
        with (
            patch.object(ClickhouseProducer, "produce", return_value=_failed_produce()),
            self.assertRaisesRegex(SplitError, "may still show 2 .* also failed: Kafka is down. Do not run a merge"),
        ):
            self._split_failing_partway()

    @parameterized.expand(
        [
            ("listed_inline", ["id2"], 10, False),
            ("read_from_a_file", ["id2", " padded id ", " ", "carriage\rreturn"], 0, True),
            ("a_distinct_id_with_a_newline_stays_inline", ["two\nlines"], 0, False),
        ]
    )
    def test_a_split_that_cannot_be_sent_again_names_the_command_that_finishes_it(
        self, _name, distinct_ids, inline_ids, from_file
    ) -> None:
        with (
            patch("posthog.models.person.divergence.detach._INLINE_DISTINCT_IDS", inline_ids),
            patch.object(ClickhouseProducer, "produce", return_value=_failed_produce()),
            self.assertRaisesRegex(SplitError, "Do not run a merge") as raised,
        ):
            self._split_losing_its_messages(distinct_ids)

        command = shlex.split(str(raised.exception).split("Run: python manage.py ")[1])
        assert ("--distinct-ids-file" in command) == from_file
        if from_file:
            self.addCleanup(Path(command[command.index("--distinct-ids-file") + 1]).unlink)
        assert command[-1] == "--apply"
        call_command(*command[:-1], stdout=StringIO())
        for distinct_id in distinct_ids:
            self._assert_clickhouse_shows_old_owner(distinct_id)
        call_command(*command, stdout=StringIO())
        for distinct_id in distinct_ids:
            self._assert_clickhouse_agrees_with_postgres(distinct_id)


class TestRepublishCommand(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        with mute_selected_signals():
            self.person = create_person(team=self.team, distinct_ids=["id1", "id2"])

    def _republish(self, *args: str) -> None:
        call_command(
            "person_consistency", "republish", "--team-id", str(self.team.pk), *args, "--apply", stdout=StringIO()
        )

    def test_a_person_uuid_in_any_spelling_is_republished(self) -> None:
        self._republish("--person-uuid", str(self.person.uuid).upper())

        assert (
            observe.ch_person_states(self.team.pk, [str(self.person.uuid)])[str(self.person.uuid)].live_max_version
            is not None
        )

    @parameterized.expand(
        [
            ("nothing_named", [], "name at least one"),
            ("a_person_uuid_that_is_not_a_uuid", ["--person-uuid", "not-a-uuid"], "must be a uuid"),
            ("a_distinct_id_not_live_in_postgres", ["--distinct-id", "ghost"], "may still disagree .* ghost"),
        ]
    )
    def test_republish_fails_when_it_cannot_confirm_a_named_key(self, _name, args, error) -> None:
        with self.assertRaisesRegex(CommandError, error):
            self._republish(*args)

    def test_republish_fails_for_a_distinct_id_whose_owner_has_too_many_distinct_ids(self) -> None:
        with (
            patch("posthog.models.person.divergence.repair_plan._MAX_REPAIR_DISTINCT_IDS_PER_PERSON", 1),
            self.assertRaisesRegex(CommandError, "may still disagree .* id2"),
        ):
            self._republish("--distinct-id", "id2")

        assert observe.ch_mapping_states(self.team.pk, ["id2"]).get("id2") is None

    def test_republish_fails_for_a_named_person_whose_mapping_was_not_delivered(self) -> None:
        def produce(*args: Any, **kwargs: Any) -> ProduceResult:
            if kwargs["topic"] == KAFKA_PERSON_DISTINCT_ID:
                return _failed_produce()
            delivered = ProduceResult(topic=kwargs["topic"])
            delivered.set_result(None, None)
            return delivered

        with (
            patch.object(ClickhouseProducer, "produce", side_effect=produce),
            self.assertRaisesRegex(CommandError, f"may still disagree .* {self.person.uuid}"),
        ):
            self._republish("--person-uuid", str(self.person.uuid))

    def test_a_replica_listing_a_distinct_id_under_its_old_person_does_not_confirm_it(self) -> None:
        with mute_selected_signals():
            new_owner = create_person(team=self.team, distinct_ids=["moved"])
        _insert_ch_mapping(self.team.pk, "moved", str(self.person.uuid))

        def lagging_replica(team_id: int, person_ids: list[int], **kwargs: Any) -> dict[int, list[DistinctIdForPerson]]:
            by_person = _batched_get_distinct_ids_for_persons(team_id, person_ids, **kwargs)
            by_person[new_owner.pk] = [d for d in by_person.get(new_owner.pk, []) if d.id != "moved"]
            by_person.setdefault(self.person.pk, []).append(DistinctIdForPerson(id="moved", version=0))
            return by_person

        with (
            patch(
                "posthog.models.person.divergence.repair_plan._batched_get_distinct_ids_for_persons",
                side_effect=lagging_replica,
            ),
            self.assertRaisesRegex(CommandError, "may still disagree with Postgres for 1 named keys: moved\\."),
        ):
            self._republish("--person-uuid", str(self.person.uuid), "--distinct-id", "moved")
