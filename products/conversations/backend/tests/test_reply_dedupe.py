from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.comment import Comment
from posthog.redis import get_client

from products.conversations.backend import reply_dedupe
from products.conversations.backend.reply_dedupe import (
    CreateOutcome,
    ReplyFingerprint,
    ReservationState,
    create_deduplicated,
    reserve,
)


class _DroppedBeforeTheWrite:
    def set(self, *args, **kwargs):
        raise ConnectionError("connection reset before the write")


class _DroppedAfterTheWrite:
    # The reservation lands and its reply is lost, so a retry finds its own token in the key.
    def __init__(self, client):
        self._client = client

    def set(self, *args, **kwargs):
        self._client.set(*args, **kwargs)
        raise TimeoutError("the reply never arrived")


class TestReplyDedupe(BaseTest):
    def setUp(self):
        super().setUp()
        # fakeredis keeps one FakeServer per process, and TEST_clear_clients() drops the client
        # without dropping its data, so reservations would otherwise leak between tests.
        get_client().flushall()
        self.item_id = "11111111-1111-4111-8111-111111111111"

    def _fingerprint(self, **overrides) -> ReplyFingerprint:
        fields: dict = {
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "scope": "conversations_ticket",
            "item_id": self.item_id,
            "content": "Have you tried clearing the cache?",
            "rich_content": None,
            "item_context": {"author_type": "support", "is_private": False},
        }
        fields.update(overrides)
        fingerprint = ReplyFingerprint.build(**fields)
        assert fingerprint is not None
        return fingerprint

    def _create_comment(self, **overrides) -> Comment:
        fields: dict = {
            "team": self.team,
            "created_by": self.user,
            "scope": "conversations_ticket",
            "item_id": self.item_id,
            "content": "Have you tried clearing the cache?",
            "item_context": {"author_type": "support", "is_private": False},
        }
        fields.update(overrides)
        return Comment.objects.create(**fields)

    def test_identical_requests_produce_one_key(self):
        assert self._fingerprint().key == self._fingerprint().key

    @parameterized.expand(
        [
            ("privacy", {"item_context": {"author_type": "support", "is_private": True}}),
            ("content", {"content": "Different body"}),
            ("ticket", {"item_id": "22222222-2222-4222-8222-222222222222"}),
            ("thread_parent", {"source_comment_id": "33333333-3333-4333-8333-333333333333"}),
            ("author", {"created_by_id": 987654}),
            ("rich_content", {"rich_content": {"type": "doc", "content": []}}),
        ]
    )
    def test_distinguishing_fields_change_the_key(self, _name: str, overrides: dict):
        assert self._fingerprint(**overrides).key != self._fingerprint().key

    def test_key_carries_no_message_content(self):
        secret = "customer account number 4242"
        assert secret not in self._fingerprint(content=secret).key

    @parameterized.expand(
        [
            ("dashboard_comment", {"scope": "Dashboard"}),
            ("internal_ticket_discussion", {"scope": "Ticket"}),
            ("customer_message", {"item_context": {"author_type": "customer", "is_private": False}}),
            ("task", {"is_task": True}),
            ("emoji_reaction", {"item_context": {"author_type": "support", "is_emoji": True}}),
            ("explicit_mentions_or_slug", {"has_unverifiable_metadata": True}),
            ("no_ticket", {"item_id": None}),
            ("no_author", {"created_by_id": None}),
        ]
    )
    def test_ineligible_requests_are_not_deduplicated(self, _name: str, overrides: dict):
        fields: dict = {
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "scope": "conversations_ticket",
            "item_id": self.item_id,
            "content": "Have you tried clearing the cache?",
            "rich_content": None,
            "item_context": {"author_type": "support", "is_private": False},
        }
        fields.update(overrides)
        assert ReplyFingerprint.build(**fields) is None

    def test_retry_replays_the_first_message_without_creating_a_second(self):
        first = create_deduplicated(self._fingerprint(), self._create_comment)
        second = create_deduplicated(self._fingerprint(), self._fail_if_called)

        assert first.outcome is CreateOutcome.CREATED
        assert second.outcome is CreateOutcome.REPLAYED
        assert second.comment is not None and second.comment.id == first.comment.id  # type: ignore[union-attr]
        assert Comment.objects.count() == 1

    def test_concurrent_attempt_conflicts_instead_of_creating(self):
        reserve(self._fingerprint())

        guarded = create_deduplicated(self._fingerprint(), self._fail_if_called)

        assert guarded.outcome is CreateOutcome.CONFLICT
        assert guarded.comment is None

    def test_released_reservation_lets_an_immediate_retry_through(self):
        fingerprint = self._fingerprint()
        with self.assertRaises(RuntimeError):
            create_deduplicated(fingerprint, self._raise_before_persisting)

        guarded = create_deduplicated(fingerprint, self._create_comment)

        assert guarded.outcome is CreateOutcome.CREATED

    def test_failure_after_the_row_persists_still_blocks_a_duplicate(self):
        fingerprint = self._fingerprint()
        with self.assertRaises(RuntimeError):
            create_deduplicated(fingerprint, self._persist_then_raise)

        guarded = create_deduplicated(fingerprint, self._fail_if_called)

        assert guarded.outcome is CreateOutcome.REPLAYED
        assert Comment.objects.count() == 1

    def test_committed_row_is_replayed_when_publication_never_landed(self):
        # The create/publish crash window: the row exists but Redis has no mapping for it, so only
        # the recent-row lookup can stop the retry from posting the message twice.
        existing = self._create_comment()

        guarded = create_deduplicated(self._fingerprint(), self._fail_if_called)

        assert guarded.outcome is CreateOutcome.REPLAYED
        assert guarded.comment is not None and guarded.comment.id == existing.id

    @parameterized.expand(
        [
            ("deleted", {"deleted": True}),
            ("edited", {"version": 3}),
            ("different_privacy", {"item_context": {"author_type": "support", "is_private": True}}),
        ]
    )
    def test_a_row_that_no_longer_matches_is_not_replayed(self, _name: str, overrides: dict):
        self._create_comment(**overrides)

        guarded = create_deduplicated(self._fingerprint(), self._create_comment)

        assert guarded.outcome is CreateOutcome.CREATED

    def test_stale_mapping_does_not_serve_an_unrelated_row(self):
        fingerprint = self._fingerprint()
        create_deduplicated(fingerprint, self._create_comment)
        Comment.objects.update(content="edited by someone else", version=1)

        guarded = create_deduplicated(fingerprint, self._create_comment)

        assert guarded.outcome is CreateOutcome.CREATED

    def test_a_message_older_than_the_replay_window_is_not_replayed(self):
        old = self._create_comment()
        Comment.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(seconds=reply_dedupe.REPLAY_WINDOW_SECONDS + 60)
        )

        guarded = create_deduplicated(self._fingerprint(), self._create_comment)

        assert guarded.outcome is CreateOutcome.CREATED

    @parameterized.expand(
        [
            ("another_attempt_holds_it", "inflight:abc", ReservationState.IN_FLIGHT),
            # A value we can't parse must not block the message; the recent-row lookup guards the create.
            ("unparseable", "garbage", ReservationState.ACQUIRED),
        ]
    )
    def test_an_existing_reservation_value_decides_the_state(self, _name: str, stored: str, expected: ReservationState):
        fingerprint = self._fingerprint()
        get_client().set(fingerprint.key, stored)

        assert reserve(fingerprint).state is expected

    @parameterized.expand(
        [
            ("the_write_never_ran", lambda client: _DroppedBeforeTheWrite()),
            ("the_write_landed_and_its_reply_was_lost", lambda client: _DroppedAfterTheWrite(client)),
        ]
    )
    def test_one_dropped_connection_does_not_give_up_the_reservation(self, _name: str, flaky_client):
        # Failing open on the first error hands back an ownerless reservation, and two concurrent
        # attempts then both create the message. A single reset connection must not cost that.
        client = get_client()

        with patch.object(reply_dedupe, "get_client", side_effect=[flaky_client(client), client]):
            reservation = reserve(self._fingerprint())

        assert reservation.state is ReservationState.ACQUIRED
        assert reservation.owner_token is not None

    def test_redis_failure_falls_back_to_the_database(self):
        # Losing Redis must degrade to database-backed replay detection, not to duplicate messages.
        existing = self._create_comment()

        with patch.object(reply_dedupe, "get_client", side_effect=ConnectionError("redis down")):
            guarded = create_deduplicated(self._fingerprint(), self._fail_if_called)

        assert guarded.outcome is CreateOutcome.REPLAYED
        assert guarded.comment is not None and guarded.comment.id == existing.id

    def _fail_if_called(self) -> Comment:
        raise AssertionError("the guard should not have created a second message")

    def _raise_before_persisting(self) -> Comment:
        raise RuntimeError("validation blew up before the insert")

    def _persist_then_raise(self) -> Comment:
        self._create_comment()
        raise RuntimeError("mention fan-out failed after the insert")
