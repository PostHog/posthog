from unittest.mock import MagicMock, patch

from django.test import TestCase

from products.conversations.backend.cache import (
    MESSAGES_CACHE_TTL,
    TICKETS_CACHE_TTL,
    get_cached_messages,
    get_cached_tickets,
    get_messages_cache_key,
    get_tickets_cache_key,
    invalidate_messages_cache,
    invalidate_tickets_cache,
    set_cached_messages,
    set_cached_tickets,
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
    def test_invalidate_messages_uses_delete_pattern(self, mock_cache):
        mock_cache.delete_pattern = MagicMock()

        invalidate_messages_cache(team_id=1, ticket_id="abc")

        mock_cache.delete_pattern.assert_called_once_with("conversations:messages:1:abc:*")

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_messages_falls_back_to_delete(self, mock_cache):
        del mock_cache.delete_pattern

        invalidate_messages_cache(team_id=1, ticket_id="abc")

        mock_cache.delete.assert_called_once_with("conversations:messages:1:abc:initial")

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_messages_swallows_exception(self, mock_cache):
        mock_cache.delete_pattern = MagicMock(side_effect=Exception("Redis error"))

        # Should not raise
        invalidate_messages_cache(team_id=1, ticket_id="abc")


class TestTicketsCacheOperations(TestCase):
    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_tickets_returns_cached_data(self, mock_cache):
        mock_cache.get.return_value = {"count": 5, "results": []}

        result = get_cached_tickets(team_id=1, widget_session_id="session")

        assert result == {"count": 5, "results": []}

    @patch("products.conversations.backend.cache.cache")
    def test_get_cached_tickets_with_status_filter(self, mock_cache):
        mock_cache.get.return_value = {"count": 2}

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
        data = {"count": 1, "results": []}

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
    def test_invalidate_tickets_uses_delete_pattern(self, mock_cache):
        mock_cache.delete_pattern = MagicMock()

        invalidate_tickets_cache(team_id=1, widget_session_id="session")

        mock_cache.delete_pattern.assert_called_once_with("conversations:tickets:1:session:*")

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_tickets_falls_back_to_delete(self, mock_cache):
        del mock_cache.delete_pattern

        invalidate_tickets_cache(team_id=1, widget_session_id="session")

        mock_cache.delete.assert_called_once_with("conversations:tickets:1:session:all")

    @patch("products.conversations.backend.cache.cache")
    def test_invalidate_tickets_swallows_exception(self, mock_cache):
        mock_cache.delete_pattern = MagicMock(side_effect=Exception("Redis error"))

        # Should not raise
        invalidate_tickets_cache(team_id=1, widget_session_id="session")
