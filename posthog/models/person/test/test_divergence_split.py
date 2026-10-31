from io import StringIO

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.utils.timezone import now

from confluent_kafka import KafkaError
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer, ProduceResult
from posthog.kafka_client.topics import KAFKA_PERSON
from posthog.models.person.divergence import observe
from posthog.models.person.divergence.detach import SplitError, split_distinct_ids
from posthog.models.person.sql import BULK_INSERT_PERSON_DISTINCT_ID2
from posthog.models.person.util import (
    create_person as create_person_in_ch,
    get_distinct_id_rows,
)
from posthog.models.signals import mute_selected_signals
from posthog.personhog_client.fake_client import fake_personhog_client
from posthog.test.persons import create_person

PERSON_UUID = "00000000-0000-0000-0000-0000000000a1"


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

    def test_a_failed_split_still_waits_for_the_messages_it_already_sent(self, *_mocks):
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.person.Person.split_person", side_effect=RuntimeError("batch 2 failed")),
            patch("posthog.models.person.divergence.detach.flush_all_producers", return_value=0) as flush,
        ):
            fake.add_person(team_id=self.team.id, person_id=501, uuid=PERSON_UUID, distinct_ids=["id1", "id2"])

            with self.assertRaisesRegex(RuntimeError, "batch 2 failed"):
                split_distinct_ids(self.team.id, PERSON_UUID, ["id2"], apply=True, log=lambda _: None)

            flush.assert_called_once()


class TestSplitLostInClickHouse(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        with mute_selected_signals():
            self.person = create_person(team=self.team, distinct_ids=["id1", "id2"])
        create_person_in_ch(team_id=self.team.pk, uuid=str(self.person.uuid), version=0, timestamp=now())
        for distinct_id in ["id1", "id2"]:
            self._ch_mapping(distinct_id, str(self.person.uuid))

    def _ch_mapping(self, distinct_id: str, person_uuid: str) -> None:
        sync_execute(
            BULK_INSERT_PERSON_DISTINCT_ID2,
            [
                {
                    "distinct_id": distinct_id,
                    "person_id": person_uuid,
                    "team_id": self.team.pk,
                    "is_deleted": 0,
                    "version": 0,
                    "_timestamp": now().replace(tzinfo=None),
                    "_offset": 0,
                    "_partition": 0,
                }
            ],
            flush=False,
        )

    def _split_losing_its_messages(self) -> list[str]:
        # The split's own publishes never reach ClickHouse, and Kafka reports them undelivered.
        with (
            patch("posthog.models.person.util.create_person"),
            patch("posthog.models.person.util.create_person_distinct_id"),
            patch("posthog.models.person.divergence.detach.flush_all_producers", return_value=2),
        ):
            return split_distinct_ids(self.team.pk, str(self.person.uuid), ["id2"], apply=True, log=lambda _: None)

    def _assert_clickhouse_agrees_with_postgres(self, distinct_id: str) -> None:
        owner = get_distinct_id_rows(self.team.pk, [distinct_id], strong=True)[0].person_uuid
        assert owner != str(self.person.uuid)
        assert observe.ch_mapping_states(self.team.pk, [distinct_id])[distinct_id].winner_person_uuid == owner
        assert observe.ch_person_states(self.team.pk, [owner])[owner].live_max_version is not None

    def test_a_split_clickhouse_missed_is_sent_again_so_no_scan_suggests_merging_it_back(self) -> None:
        assert self._split_losing_its_messages() == ["id2"]

        self._assert_clickhouse_agrees_with_postgres("id2")
        assert observe.ch_mapping_states(self.team.pk, ["id1"])["id1"].winner_person_uuid == str(self.person.uuid)

    def test_a_split_that_cannot_be_sent_again_names_the_command_that_finishes_it(self) -> None:
        failed = ProduceResult(topic=KAFKA_PERSON)
        failed.set_result(KafkaError(-192, "Local: Message timed out"), None)

        with (
            patch.object(ClickhouseProducer, "produce", return_value=failed),
            self.assertRaisesRegex(SplitError, "Do not run a merge") as raised,
        ):
            self._split_losing_its_messages()

        command = f"person_consistency republish --team-id {self.team.pk} --distinct-id id2"
        assert f"{command} --apply" in str(raised.exception)
        call_command(*command.split(), stdout=StringIO())
        assert observe.ch_mapping_states(self.team.pk, ["id2"])["id2"].winner_person_uuid == str(self.person.uuid)
        call_command(*command.split(), "--apply", stdout=StringIO())
        self._assert_clickhouse_agrees_with_postgres("id2")

    def test_republish_command_needs_a_person_or_distinct_id(self) -> None:
        with self.assertRaisesRegex(CommandError, "name at least one"):
            call_command("person_consistency", "republish", "--team-id", str(self.team.pk), stdout=StringIO())
