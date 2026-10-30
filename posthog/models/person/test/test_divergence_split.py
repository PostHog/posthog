from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.person.divergence.detach import SplitError, split_distinct_ids
from posthog.personhog_client.fake_client import fake_personhog_client

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

    def test_undelivered_clickhouse_messages_fail_the_split(self, *_mocks):
        with (
            fake_personhog_client() as fake,
            patch("posthog.models.person.divergence.detach.flush_all_producers", return_value=2),
        ):
            fake.add_person(team_id=self.team.id, person_id=501, uuid=PERSON_UUID, distinct_ids=["id1", "id2"])

            with self.assertRaisesRegex(SplitError, "2 ClickHouse messages were not delivered"):
                split_distinct_ids(self.team.id, PERSON_UUID, ["id2"], apply=True, log=lambda _: None)

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
