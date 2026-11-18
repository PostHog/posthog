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
    EmojiSearchRequestSerializer,
    EmojiSearchThrottle,
    EmojiSearchUnavailable,
    EmojiSearchViewSet,
)
from posthog.auth import (
    JwtAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    SessionAuthentication,
)
from posthog.emoji_search.match import EmojiSearchResult, EmojiSuggestion
from posthog.llm.system_one import SystemOneNotConfigured


class TestEmojiSearch(SimpleTestCase):
    def test_request_throttle_keeps_cached_results_available(self) -> None:
        assert EmojiSearchViewSet.throttle_classes == [EmojiSearchThrottle]

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

        for cacheable, cache_control in ((True, "private, max-age=604800"), (False, "no-store")):
            with self.subTest(cacheable=cacheable):
                result = EmojiSearchResult([EmojiSuggestion("🦖", "T-Rex")], cacheable=cacheable)
                with patch("posthog.api.emoji_search.suggest_emojis", return_value=result) as suggest:
                    response = view.suggest(request)

                assert response.status_code == status.HTTP_200_OK
                assert response.data == {"suggestions": [{"emoji": "🦖", "label": "T-Rex"}]}
                assert response["Cache-Control"] == cache_control
                assert set(response["Vary"].split(", ")) == {"Cookie", "Authorization"}
                suggest.assert_called_once_with("jurassic park", team_id=1)

    def test_unavailable(self) -> None:
        view = EmojiSearchViewSet()
        view.team_id = 1
        request = SimpleNamespace(query_params={"query": "jurassic park"})

        with patch("posthog.api.emoji_search.suggest_emojis", side_effect=SystemOneNotConfigured):
            with self.assertRaises(EmojiSearchUnavailable):
                view.suggest(request)
