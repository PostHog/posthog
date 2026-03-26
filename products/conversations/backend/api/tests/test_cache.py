from unittest.mock import patch

from django.test import TestCase

from products.conversations.backend.cache import (
    MESSAGES_CACHE_TTL,
    TICKETS_CACHE_TTL,
    UNREAD_COUNT_CACHE_TTL,
    get_cached_messages,
    get_cached_tickets,
    get_cached_unread_count,
    get_messages_cache_key,
    get_tickets_cache_key,
    get_unread_count_cache_key,
    invalidate_messages_cache,
    invalidate_tickets_cache,
    invalidate_unread_count_cache,
    set_cached_messages,
    set_cached_tickets,
    set_cached_unread_count,
)


class TestCacheKeyGeneration(TestCase):
    def test_messages_cache_key_without_after(self):
        key = get_messages_cache_key(team_id=1, ticket_id="abc-123")
        assert key == "conversations:messages:1:abc-123:initial"

    def test_messages_cache_key_with_after(self):
        key = get_messages_cache_key(team_id=1, ticket_id="abc-123", after="2024-01-01T00:00:00")
        assert key == "conversations:messages:1:abc-123:2024-01-01T00:00:00"

    def test_tickets_cache_key_without_status(self):
        key = get_tickets_cache_key(team_id=1, widget_session_id="session-123")
        assert key == "conversations:tickets:1:session-123:all"

    def test_tickets_cache_key_with_status(self):
        key = get_tickets_cache_key(team_id=1, widget_session_id="session-123", status="open")
        assert key == "conversations:tickets:1:session-123:open"

    def test_unread_count_cache_key(self):
        key = get_unread_count_cache_key(team_id=42)
        assert key == "conversations:unread_count:42"


class TestMessagesCacheOperations(TestCase):
    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_messages_returns_cached_data(self, mock_cache):
        mock_cache.get.return_value = {"messages": []}

        result = get_cached_messages(team_id=1, ticket_id="abc")

        assert result == {"messages": []}
        mock_cache.get.assert_called_once()

    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_messages_returns_none_on_miss(self, mock_cache):
        mock_cache.get.return_value = None

        result = get_cached_messages(team_id=1, ticket_id="abc")

        assert result is None

    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_messages_returns_none_on_exception(self, mock_cache):
        mock_cache.get.side_effect = Exception("Redis error")

        result = get_cached_messages(team_id=1, ticket_id="abc")

        assert result is None

    @patch("products.conversations.backend.cache.cache")
    def test_set_cached_messages_sets_with_ttl(self, mock_cache):
        data = {"messages": [{"id": "1"}]}

        set_cached_messages(team_id=1, ticket_id="abc", response_data=data)

        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][1] == data
        assert call_args[1]["timeout"] == MESSAGES_CACHE_TTL

    @patch("products.conversations.backend.cache.cache")
    def test_set_cached_messages_swallows_exception(self, mock_cache):
        mock_cache.set.side_effect = Exception("Redis error")

        # Should not raise
        set_cached_messages(team_id=1, ticket_id="abc", response_data={})

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_messages_cache_deletes_key(self, mock_cache):
        invalidate_messages_cache(team_id=1, ticket_id="abc-123")

        mock_cache.delete.assert_called_once()
        call_key = mock_cache.delete.call_args[0][0]
        assert "messages" in call_key
        assert "abc-123" in call_key

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_messages_cache_swallows_exception(self, mock_cache):
        mock_cache.delete.side_effect = Exception("Redis error")

        # Should not raise
        invalidate_messages_cache(team_id=1, ticket_id="abc")


class TestTicketsCacheOperations(TestCase):
    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_tickets_returns_cached_data(self, mock_cache):
        mock_cache.get.return_value = {"results": [], "has_more": False}

        result = get_cached_tickets(team_id=1, widget_session_id="session")

        assert result == {"results": [], "has_more": False}

    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_tickets_with_status_filter(self, mock_cache):
        mock_cache.get.return_value = {"results": []}

        get_cached_tickets(team_id=1, widget_session_id="session", status="open")

        call_key = mock_cache.get.call_args[0][0]
        assert "open" in call_key

    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_tickets_returns_none_on_exception(self, mock_cache):
        mock_cache.get.side_effect = Exception("Redis error")

        result = get_cached_tickets(team_id=1, widget_session_id="session")

        assert result is None

    @patch("products.conversations.backend.cache.cache")
    def test_set_cached_tickets_sets_with_ttl(self, mock_cache):
        data = {"results": [], "has_more": False}

        set_cached_tickets(team_id=1, widget_session_id="session", response_data=data)

        call_args = mock_cache.set.call_args
        assert call_args[0][1] == data
        assert call_args[1]["timeout"] == TICKETS_CACHE_TTL

    @patch("products.conversations.backend.cache.cache")
    def test_set_cached_tickets_swallows_exception(self, mock_cache):
        mock_cache.set.side_effect = Exception("Redis error")

        # Should not raise
        set_cached_tickets(team_id=1, widget_session_id="session", response_data={})

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_tickets_cache_deletes_all_status_variants(self, mock_cache):
        invalidate_tickets_cache(team_id=1, widget_session_id="session-123")

        mock_cache.delete_many.assert_called_once()
        deleted_keys = mock_cache.delete_many.call_args[0][0]
        # Should include unfiltered ("all") + every Status enum value
        assert any("all" in k for k in deleted_keys)
        assert any("open" in k for k in deleted_keys)
        assert any("resolved" in k for k in deleted_keys)
        assert any("new" in k for k in deleted_keys)
        assert len(deleted_keys) == 6  # None + 5 statuses

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_tickets_cache_swallows_exception(self, mock_cache):
        mock_cache.delete_many.side_effect = Exception("Redis error")

        # Should not raise
        invalidate_tickets_cache(team_id=1, widget_session_id="session")


class TestUnreadCountCacheOperations(TestCase):
    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_unread_count_returns_cached_data(self, mock_cache):
        mock_cache.get.return_value = 5

        result = get_cached_unread_count(team_id=1)

        assert result == 5
        mock_cache.get.assert_called_once()

    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_unread_count_returns_none_on_miss(self, mock_cache):
        mock_cache.get.return_value = None

        result = get_cached_unread_count(team_id=1)

        assert result is None

    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_unread_count_returns_none_on_exception(self, mock_cache):
        mock_cache.get.side_effect = Exception("Redis error")

        result = get_cached_unread_count(team_id=1)

        assert result is None

    @patch("products.conversations.backend.cache.cache")
    def test_set_cached_unread_count_sets_with_ttl(self, mock_cache):
        set_cached_unread_count(team_id=1, count=10)

        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][1] == 10
        assert call_args[1]["timeout"] == UNREAD_COUNT_CACHE_TTL

    @patch("products.conversations.backend.cache.cache")
    def test_set_cached_unread_count_swallows_exception(self, mock_cache):
        mock_cache.set.side_effect = Exception("Redis error")

        # Should not raise
        set_cached_unread_count(team_id=1, count=5)

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_unread_count_cache_deletes_key(self, mock_cache):
        invalidate_unread_count_cache(team_id=1)

        mock_cache.delete.assert_called_once()
        call_key = mock_cache.delete.call_args[0][0]
        assert "unread_count" in call_key
        assert "1" in call_key

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_unread_count_cache_swallows_exception(self, mock_cache):
        mock_cache.delete.side_effect = Exception("Redis error")

        # Should not raise
        invalidate_unread_count_cache(team_id=1)
