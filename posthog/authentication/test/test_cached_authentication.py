"""
Tests for cached token authentication backend.
"""

import json

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import RequestFactory

from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.request import Request

from posthog.auth import SecuredSDKEndpointUser
from posthog.authentication.cached_authentication import LocalEvaluationAuthentication
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal
from posthog.storage.team_access_cache import team_access_cache


class TestLocalEvaluationAuthentication(APIBaseTest):
    """Test the LocalEvaluationAuthentication class."""

    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.factory = RequestFactory()
        self.auth = LocalEvaluationAuthentication()
        self.access_token = "phs_SECRETAPITOKEN"
        self.hashed_token = hash_key_value(self.access_token, mode="sha256")

        # Set up the team with the secret API token
        self.team.secret_api_token = self.access_token
        self.team.save()
        self.project_api_key = self.team.api_token

    def test_authenticate_header(self):
        """Test authenticate_header returns correct keyword."""
        request = self.factory.get("/")
        header = self.auth.authenticate_header(request)
        assert header == "Bearer"

    def test_authenticate_no_tokens(self):
        """Test authentication with no tokens in request."""
        request = self.factory.post("/", content_type="application/json")
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth.authenticate(drf_request)
        assert result is None

    def test_extract_project_api_key_from_body(self):
        """Test extracting project API key from request body."""
        data = json.dumps({"project_api_key": self.project_api_key, "other_field": "value"})
        request = self.factory.post("/", data, content_type="application/json")
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth._extract_project_api_key(drf_request)
        assert result == self.project_api_key

    def test_extract_project_api_key_from_query(self):
        """Test extracting project API key from query parameters."""
        request = self.factory.get("/", {"project_api_key": self.project_api_key, "other_param": "value"})
        drf_request = Request(request)

        result = self.auth._extract_project_api_key(drf_request)
        assert result == self.project_api_key

    def test_extract_project_api_key_alternative_name(self):
        """Test extracting project API key using alternative field name."""
        data = json.dumps({"api_key": self.project_api_key})
        request = self.factory.post("/", data, content_type="application/json")
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth._extract_project_api_key(drf_request)
        assert result == self.project_api_key

    def test_extract_access_token_personal_key(self):
        """Test extracting personal API key as access token."""

        request = self.factory.post(
            "/", content_type="application/json", HTTP_AUTHORIZATION="Bearer phx_personalapitoken"
        )
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth._extract_access_token(drf_request)
        assert result == ("phx_personalapitoken", "personal_api_key")

    def test_extract_access_token_secret_key(self):
        """Test extracting secret API key as access token."""

        request = self.factory.post(
            "/", content_type="application/json", HTTP_AUTHORIZATION="Bearer phs_supersecrettoken"
        )
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth._extract_access_token(drf_request)
        assert result == ("phs_supersecrettoken", "secret_api_key")

    @patch("posthog.auth.PersonalAPIKeyAuthentication.find_key")
    @patch("posthog.auth.ProjectSecretAPIKeyAuthentication.find_secret_api_token")
    def test_extract_tokens_complete(self, mock_secret, mock_personal):
        """Test complete token extraction."""
        mock_personal.return_value = None
        mock_secret.return_value = self.access_token

        data = json.dumps({"project_api_key": self.project_api_key})
        request = self.factory.post("/", data, content_type="application/json")
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth._extract_tokens(drf_request)

        assert result is not None
        project_key, access_token, token_type = result
        assert project_key == self.project_api_key
        assert access_token == self.access_token
        assert token_type == "secret_api_key"

    def test_authenticate_with_cache_success(self):
        """Test successful cached authentication."""
        # Actually put the token in the cache
        team_access_cache.update_team_tokens(self.project_api_key, self.team.id, [self.hashed_token])

        result = self.auth._authenticate_with_cache(self.project_api_key, self.access_token, "secret_api_key")

        assert isinstance(result, SecuredSDKEndpointUser)
        assert result.team.id == self.team.id

    def test_authenticate_with_cache_miss(self):
        """Test cache miss in cached authentication."""
        # Clear any existing cache and use a token that doesn't exist in database
        team_access_cache.invalidate_team(self.project_api_key)
        fake_secret_token = "phs_NONEXISTENT_SECRET_TOKEN"

        result = self.auth._authenticate_with_cache(self.project_api_key, fake_secret_token, "secret_api_key")

        assert result is None

    def test_authenticate_with_cache_no_team(self):
        """Test cached authentication when team is not found."""
        # Use a fake secret API token that doesn't belong to any team
        fake_secret_token = "phs_NONEXISTENT_SECRET_TOKEN"
        fake_hashed_token = hash_key_value(fake_secret_token, mode="sha256")

        # Put the fake token in cache
        team_access_cache.update_team_tokens(self.project_api_key, self.team.id, [fake_hashed_token])

        result = self.auth._authenticate_with_cache(self.project_api_key, fake_secret_token, "secret_api_key")

        assert isinstance(result, SecuredSDKEndpointUser)
        assert result.team.id == self.team.id

    def test_authenticate_with_cache_personal_key_success(self):
        """Test that personal API keys with valid scopes succeed in cached auth."""
        # Create a real personal API key with proper token format and valid scopes
        personal_token = generate_random_token_personal()  # Creates "phx_..." token
        personal_hashed = hash_key_value(personal_token, mode="sha256")
        # Put the personal API key token in cache
        team_access_cache.update_team_tokens(self.project_api_key, self.team.id, [personal_hashed])

        result = self.auth._authenticate_with_cache(self.project_api_key, personal_token, "personal_api_key")

        assert isinstance(result, SecuredSDKEndpointUser)
        assert result.team.id == self.team.id

    @patch("posthog.storage.team_access_cache.team_access_cache.has_access_with_team")
    def test_full_authenticate_cache_hit(self, mock_has_access):
        """Test full authentication flow with cache hit."""
        # Mock the cache to return True (token is authorized)
        mock_has_access.return_value = True, self.team

        data = json.dumps({"project_api_key": self.project_api_key})
        request = self.factory.post(
            "/", data, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.access_token}"
        )
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth.authenticate(drf_request)

        assert result is not None
        user, auth = result
        assert isinstance(user, SecuredSDKEndpointUser)
        assert user.team.id == self.team.id

    def test_full_authenticate_cache_miss_with_warming(self):
        """Test full authentication flow with cache miss that warms successfully."""
        # Clear any existing cache to ensure this is a real cache miss initially
        team_access_cache.invalidate_team(self.project_api_key)

        data = json.dumps({"project_api_key": self.project_api_key})
        request = self.factory.post(
            "/", data, content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {self.access_token}"
        )
        drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

        result = self.auth.authenticate(drf_request)

        # Should succeed because cache warming finds the valid token
        assert result is not None
        user, auth = result
        assert isinstance(user, SecuredSDKEndpointUser)
        assert user.team.id == self.team.id

    def test_full_authenticate_handles_exceptions(self):
        """Test that authentication handles unexpected exceptions gracefully."""
        with patch.object(self.auth, "_extract_tokens", side_effect=Exception("Unexpected error")):
            request = self.factory.post("/", content_type="application/json")
            drf_request = Request(request, parsers=[JSONParser(), FormParser(), MultiPartParser()])

            # Should return None instead of raising exception
            result = self.auth.authenticate(drf_request)
            assert result is None

    def test_has_feature_flag_access_with_read_scope(self):
        """Test that personal API keys with feature_flag:read scope have access."""
        user = User.objects.create(email="scope1@example.com")
        personal_key = PersonalAPIKey.objects.create(
            label="Read Scope Key", user=user, scopes=["feature_flag:read", "insight:read"]
        )

        result = self.auth._has_feature_flag_access(personal_key)
        assert result is True

    def test_has_feature_flag_access_with_write_scope(self):
        """Test that personal API keys with feature_flag:write scope have access."""
        user = User.objects.create(email="scope2@example.com")
        personal_key = PersonalAPIKey.objects.create(
            label="Write Scope Key", user=user, scopes=["feature_flag:write", "insight:read"]
        )

        result = self.auth._has_feature_flag_access(personal_key)
        assert result is True

    def test_has_feature_flag_access_with_wildcard(self):
        """Test that personal API keys with wildcard scope have access."""
        user = User.objects.create(email="scope3@example.com")
        personal_key = PersonalAPIKey.objects.create(label="Wildcard Key", user=user, scopes=["*"])

        result = self.auth._has_feature_flag_access(personal_key)
        assert result is True

    def test_has_feature_flag_access_legacy_no_scopes(self):
        """Test that legacy personal API keys (no scopes) have access."""
        user = User.objects.create(email="scope4@example.com")
        personal_key = PersonalAPIKey.objects.create(label="Legacy Key", user=user, scopes=None)

        result = self.auth._has_feature_flag_access(personal_key)
        assert result is True

    def test_has_feature_flag_access_empty_scopes(self):
        """Test that personal API keys with empty scopes have access (legacy)."""
        user = User.objects.create(email="scope5@example.com")
        personal_key = PersonalAPIKey.objects.create(label="Empty Scopes Key", user=user, scopes=[])

        result = self.auth._has_feature_flag_access(personal_key)
        assert result is True

    def test_has_feature_flag_access_without_feature_flag_scope(self):
        """Test that personal API keys without feature flag scope are denied."""
        user = User.objects.create(email="scope6@example.com")
        personal_key = PersonalAPIKey.objects.create(
            label="No FF Scope Key", user=user, scopes=["insight:read", "cohort:write"]
        )

        result = self.auth._has_feature_flag_access(personal_key)
        assert result is False

    def test_has_feature_flag_access_handles_exceptions(self):
        """Test that scope checking handles exceptions gracefully."""
        # For this test, MagicMock is actually appropriate since we're testing exception handling
        mock_personal_key = MagicMock()
        mock_personal_key.scopes = MagicMock(side_effect=Exception("Scope error"))

        result = self.auth._has_feature_flag_access(mock_personal_key)
        assert result is False
