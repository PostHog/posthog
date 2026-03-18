from posthog.test.base import BaseTest

from django.core.cache import caches

from ee.hogai.queue import ConversationQueueStore, QueueFullError, build_queue_message


class TestConversationQueueStore(BaseTest):
    def setUp(self):
        super().setUp()
        self.store = ConversationQueueStore("conversation-test", max_messages=2)
        caches["default"].delete(self.store._cache_key())

    def test_list_returns_empty_when_no_queue(self):
        self.assertEqual(self.store.list(), [])

    def test_enqueue_adds_message(self):
        message = build_queue_message(content="hello")
        queue_messages = self.store.enqueue(message)
        self.assertEqual(queue_messages, [message])
        self.assertEqual(self.store.list(), [message])

    def test_enqueue_raises_when_full(self):
        self.store.enqueue(build_queue_message(content="first"))
        self.store.enqueue(build_queue_message(content="second"))

        with self.assertRaises(QueueFullError):
            self.store.enqueue(build_queue_message(content="third"))

    def test_update_modifies_existing_message(self):
        message = build_queue_message(content="hello")
        self.store.enqueue(message)

        queue_messages = self.store.update(message["id"], "updated")

        self.assertEqual(queue_messages[0]["content"], "updated")

    def test_update_returns_unchanged_for_nonexistent_id(self):
        message = build_queue_message(content="hello")
        self.store.enqueue(message)

        queue = self.store.update("missing", "updated")

        self.assertEqual(queue, [message])

    def test_delete_removes_message(self):
        message = build_queue_message(content="hello")
        self.store.enqueue(message)

        queue = self.store.delete(message["id"])

        self.assertEqual(queue, [])

    def test_pop_next_returns_first_and_removes(self):
        first = build_queue_message(content="first")
        second = build_queue_message(content="second")
        self.store.enqueue(first)
        self.store.enqueue(second)

        popped = self.store.pop_next()

        self.assertEqual(popped, first)
        self.assertEqual(self.store.list(), [second])

    def test_pop_next_returns_none_when_empty(self):
        self.assertIsNone(self.store.pop_next())

    def test_clear_empties_queue(self):
        message = build_queue_message(content="hello")
        self.store.enqueue(message)

        queue = self.store.clear()

        self.assertEqual(queue, [])
        self.assertEqual(self.store.list(), [])

    def test_requeue_front_inserts_at_start(self):
        first = build_queue_message(content="first")
        second = build_queue_message(content="second")
        self.store.enqueue(first)

        queue = self.store.requeue_front(second)

        self.assertEqual(queue, [second, first])

    def test_requeue_front_keeps_max_size(self):
        first = build_queue_message(content="first")
        second = build_queue_message(content="second")
        third = build_queue_message(content="third")
        self.store.enqueue(first)
        self.store.enqueue(second)

        queue = self.store.requeue_front(third)

        self.assertEqual(queue, [third, first])
