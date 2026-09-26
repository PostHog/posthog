import os
from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import path

from drf_spectacular.generators import SchemaGenerator
from rest_framework import status
from rest_framework.request import Request

from posthog.api.emoji_search import (
    EmojiSearchDailyThrottle,
    EmojiSearchRequestSerializer,
    EmojiSearchUnavailable,
    EmojiSearchViewSet,
)
from posthog.auth import (
    JwtAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
)
from posthog.emoji_search.match import EmojiSuggestion
from posthog.llm.system_one import SystemOneNotConfigured


class TestEmojiSearch(SimpleTestCase):
    def test_daily_throttle_is_shared_by_team(self) -> None:
        throttle = EmojiSearchDailyThrottle()
        keys = []
        for team_id, user_id in ((1, 1), (1, 2), (2, 1)):
            request = cast(Request, SimpleNamespace(user=SimpleNamespace(pk=user_id, is_authenticated=True)))
            view = EmojiSearchViewSet()
            view.team_id = team_id
            keys.append(throttle.get_cache_key(request, view))

        assert keys[0] == keys[1]
        assert keys[0] != keys[2]

    def test_only_web_app_sessions_are_allowed(self) -> None:
        permission = EmojiSearchViewSet.permission_classes[0]()
        for authenticator, allowed in (
            (SessionAuthentication(), True),
            (JwtAuthentication(), False),
            (OAuthAccessTokenAuthentication(), False),
            (PersonalAPIKeyAuthentication(), False),
        ):
            with self.subTest(authenticator=type(authenticator).__name__):
                request = cast(Request, SimpleNamespace(successful_authenticator=authenticator))
                assert permission.has_permission(request, EmojiSearchViewSet()) is allowed

    def test_query_length_is_validated(self) -> None:
        for query, expected in (("ab", False), ("abc", True)):
            with self.subTest(query=query):
                assert EmojiSearchRequestSerializer(data={"query": query}).is_valid() is expected

    def test_endpoint_is_only_in_the_codegen_schema(self) -> None:
        route = "/api/projects/{project_id}/emoji_search/suggest/"
        patterns = [
            path(
                "api/projects/<int:project_id>/emoji_search/suggest/",
                EmojiSearchViewSet.as_view({"get": "suggest"}),
            )
        ]

        with patch.dict(os.environ, {"OPENAPI_INCLUDE_INTERNAL": ""}):
            public_schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
        with patch.dict(os.environ, {"OPENAPI_INCLUDE_INTERNAL": "1", "OPENAPI_MOCK_INTERNAL_API_SECRET": "1"}):
            codegen_schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)

        assert route not in public_schema["paths"]
        assert route in codegen_schema["paths"]

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
