from datetime import timedelta
from uuid import uuid4

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.person.tombstone_log import (
    MAX_ACK_SIZE,
    TombstoneConsumer,
    ack_person_tombstones_for_consumer,
    list_pending_person_tombstones,
    list_person_tombstone_distinct_ids,
    retire_acked_person_tombstones,
)
from posthog.models.person.util import tombstone_persons_in_postgres
from posthog.personhog_client.fake_client import fake_personhog_client

TEAM_ID = 7


def _pending(consumer: TombstoneConsumer) -> list[int]:
    return [entry.log_id for entry in list_pending_person_tombstones(consumer, team_id=TEAM_ID, limit=1000).entries]


class TestTombstoneLog(SimpleTestCase):
    def test_both_consumers_ack_the_same_captured_generation(self) -> None:
        with fake_personhog_client() as fake:
            fake.tombstone_log_capture = True
            person_uuid = uuid4()
            fake.add_person(team_id=TEAM_ID, person_id=1, uuid=str(person_uuid), distinct_ids=["log-a", "log-b"])

            [tombstone] = tombstone_persons_in_postgres(TEAM_ID, [person_uuid])
            assert tombstone.log_id is not None
            identities = list_person_tombstone_distinct_ids(TEAM_ID, tombstone.log_id).identities
            assert [(i.distinct_id, i.version) for i in identities] == [("log-a", 1), ("log-b", 1)]

            ack_person_tombstones_for_consumer(TombstoneConsumer.PUBLICATION, TEAM_ID, [tombstone.log_id])
            assert _pending(TombstoneConsumer.PUBLICATION) == []
            assert _pending(TombstoneConsumer.CUSTOMER_ANALYTICS_MEMBERSHIP) == [tombstone.log_id]
            assert retire_acked_person_tombstones().retired == 0

            ack_person_tombstones_for_consumer(
                TombstoneConsumer.CUSTOMER_ANALYTICS_MEMBERSHIP, TEAM_ID, [tombstone.log_id]
            )
            assert retire_acked_person_tombstones().retired == 1
            assert list_person_tombstone_distinct_ids(TEAM_ID, tombstone.log_id).identities == ()

    def test_capture_off_reports_no_log_id(self) -> None:
        with fake_personhog_client() as fake:
            person_uuid = uuid4()
            fake.add_person(team_id=TEAM_ID, person_id=1, uuid=str(person_uuid), distinct_ids=["log-off"])

            [tombstone] = tombstone_persons_in_postgres(TEAM_ID, [person_uuid])

            assert tombstone.log_id is None
            assert _pending(TombstoneConsumer.PUBLICATION) == []

    def test_pages_hand_back_the_cursor_of_the_next_page(self) -> None:
        with fake_personhog_client() as fake:
            log_ids = [
                fake.add_tombstone_log_entry(
                    team_id=TEAM_ID,
                    person_uuid=str(uuid4()),
                    person_version=1,
                    distinct_ids=[("page-a", 1), ("page-b", 1)],
                )
                for _ in range(3)
            ]
            fake.add_tombstone_log_entry(
                team_id=TEAM_ID + 1, person_uuid=str(uuid4()), person_version=1, distinct_ids=[("other", 1)]
            )

            first = list_pending_person_tombstones(TombstoneConsumer.PUBLICATION, team_id=TEAM_ID, limit=2)
            second = list_pending_person_tombstones(
                TombstoneConsumer.PUBLICATION, team_id=TEAM_ID, limit=2, after=first.next_cursor
            )
            identities = list_person_tombstone_distinct_ids(TEAM_ID, log_ids[0], limit=1)

            assert [e.log_id for e in first.entries + second.entries] == log_ids
            assert first.next_cursor == log_ids[1]
            assert second.next_cursor is None
            assert [i.distinct_id for i in identities.identities] == ["page-a"]
            assert identities.next_cursor == identities.identities[0].id
            assert list_person_tombstone_distinct_ids(TEAM_ID + 1, log_ids[0]).identities == ()

    def test_acks_dedupe_and_stay_within_the_replica_cap(self) -> None:
        with fake_personhog_client() as fake:
            log_ids = [
                fake.add_tombstone_log_entry(
                    team_id=TEAM_ID, person_uuid=str(uuid4()), person_version=1, distinct_ids=[]
                )
                for _ in range(MAX_ACK_SIZE + 1)
            ]

            acked = ack_person_tombstones_for_consumer(TombstoneConsumer.PUBLICATION, TEAM_ID, log_ids + log_ids[:5])

            assert acked == len(log_ids)
            sizes = [len(call.request.log_ids) for call in fake.calls if call.method == "ack_person_tombstone_log"]
            assert sizes == [MAX_ACK_SIZE, 1]

    @parameterized.expand(
        [
            ("zero_limit", {"limit": 0}),
            ("limit_over_the_cap", {"limit": 1001}),
            ("negative_min_age", {"min_age": timedelta(seconds=-1)}),
        ]
    )
    def test_rejects_out_of_range_page_requests(self, _name: str, kwargs: dict) -> None:
        with fake_personhog_client():
            with self.assertRaises(ValueError):
                list_pending_person_tombstones(TombstoneConsumer.PUBLICATION, **kwargs)
