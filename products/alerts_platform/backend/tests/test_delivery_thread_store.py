from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.delivery.thread_store import (
    PENDING_CLAIM_TTL,
    DatabaseThreadStore,
    ThreadBusy,
    ThreadKey,
)
from products.alerts_platform.backend.delivery.transport import MessageHandle
from products.alerts_platform.backend.models import PlatformAlertConfiguration, PlatformAlertThread

FIRING = datetime(2026, 9, 30, 9, tzinfo=UTC)


class TestDatabaseThreadStore(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        with team_scope(self.team.id):
            self.configuration = PlatformAlertConfiguration.objects.create(
                team=self.team,
                name="API errors",
                source_kind=PlatformAlertConfiguration.SourceKind.LOGS,
                source_config={},
                threshold_count=10,
                threshold_operator="above",
                window_minutes=5,
                check_interval_minutes=10,
            )
        self.store = DatabaseThreadStore(self.team.id)

    def _key(self, grouping_key: str = "", episode: datetime = FIRING) -> ThreadKey:
        return ThreadKey(
            configuration_id=str(self.configuration.id),
            grouping_key=grouping_key,
            provider="slack",
            channel_target="C-ENG",
            episode_started_at=episode,
        )

    def test_an_evaluation_that_already_landed_is_not_sent_again(self) -> None:
        key = self._key()
        claim = self.store.claim(key, "eval-1")
        assert claim is not None
        self.store.delivered(claim, MessageHandle(external_ref={"channel": "C-ENG", "ts": "1"}))

        assert self.store.claim(key, "eval-1") is None

    def test_a_later_evaluation_replies_to_the_message_that_opened_the_thread(self) -> None:
        key = self._key()
        opener = self.store.claim(key, "eval-1")
        assert opener is not None
        self.store.delivered(opener, MessageHandle(external_ref={"channel": "C-ENG", "ts": "1"}))

        resolve = self.store.claim(key, "eval-2")
        assert resolve is not None
        assert resolve.handle == MessageHandle(external_ref={"channel": "C-ENG", "ts": "1"})

        # A reply's own handle must not replace the root's, or the next message would reply to
        # a reply and the conversation would walk away from where it started.
        self.store.delivered(resolve, MessageHandle(external_ref={"channel": "C-ENG", "ts": "2"}))
        third = self.store.claim(key, "eval-3")
        assert third is not None
        assert third.handle == MessageHandle(external_ref={"channel": "C-ENG", "ts": "1"})

    @parameterized.expand([("fresh", timedelta(seconds=1), True), ("stale", PENDING_CLAIM_TTL * 2, False)])
    def test_a_claim_blocks_another_send_until_it_goes_stale(
        self, _name: str, age: timedelta, expect_busy: bool
    ) -> None:
        key = self._key()
        first = self.store.claim(key, "eval-1")
        assert first is not None
        with team_scope(self.team.id):
            PlatformAlertThread.objects.filter(id=first.thread_id).update(pending_claimed_at=timezone.now() - age)

        if expect_busy:
            with pytest.raises(ThreadBusy):
                self.store.claim(key, "eval-2")
        else:
            assert self.store.claim(key, "eval-2") is not None

    def test_a_superseded_holder_does_not_clear_the_claim_that_replaced_it(self) -> None:
        key = self._key()
        stalled = self.store.claim(key, "eval-1")
        assert stalled is not None
        with team_scope(self.team.id):
            PlatformAlertThread.objects.filter(id=stalled.thread_id).update(
                pending_claimed_at=timezone.now() - PENDING_CLAIM_TTL * 2
            )
        successor = self.store.claim(key, "eval-2")
        assert successor is not None

        self.store.release(stalled)

        with team_scope(self.team.id):
            thread = PlatformAlertThread.objects.get(id=successor.thread_id)
        assert thread.pending_evaluation_key == "eval-2"

    def test_two_groups_of_one_configuration_get_their_own_rows(self) -> None:
        checkout = self.store.claim(self._key(grouping_key="checkout"), "eval-1")
        search = self.store.claim(self._key(grouping_key="search"), "eval-1")

        assert checkout is not None and search is not None
        assert checkout.thread_id != search.thread_id
