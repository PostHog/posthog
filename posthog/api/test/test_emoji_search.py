from types import SimpleNamespace

from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework import status

from posthog.api.emoji_search import EmojiSearchUnavailable, EmojiSearchViewSet
from posthog.emoji_search.match import EmojiSuggestion
from posthog.llm.system_one import SystemOneNotConfigured


class TestEmojiSearch(SimpleTestCase):
    def test_suggest(self) -> None:
        view = EmojiSearchViewSet()
        view.team_id = 1
        request = SimpleNamespace(query_params={"query": "jurassic park"})

        with patch("posthog.api.emoji_search.suggest_emojis", return_value=[EmojiSuggestion("🦖", "T-Rex")]) as suggest:
            response = view.suggest(request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"suggestions": [{"emoji": "🦖", "label": "T-Rex"}]}
        assert response["Cache-Control"] == "private, max-age=604800"
        assert set(response["Vary"].split(", ")) == {"Cookie", "Authorization"}
        suggest.assert_called_once_with("jurassic park", team_id=1)

    def test_unavailable(self) -> None:
        view = EmojiSearchViewSet()
        view.team_id = 1
        request = SimpleNamespace(query_params={"query": "jurassic park"})

        with patch("posthog.api.emoji_search.suggest_emojis", side_effect=SystemOneNotConfigured):
            with self.assertRaises(EmojiSearchUnavailable):
                view.suggest(request)
