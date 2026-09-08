from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from posthog.hogql.language_service import CatalogMissing, LanguageServiceClient, is_language_service_enabled

from posthog.jwt import PosthogJwtAudience, decode_jwt


@override_settings(
    HOGQL_LANGUAGE_SERVICE_URL="http://language-service:8091",
    HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=["test-language-service-signing-key"],
)
class TestLanguageServiceClient(SimpleTestCase):
    @patch("posthog.hogql.language_service.requests.request")
    def test_routes_request_and_scopes_token_to_principal_and_operation(self, request: MagicMock) -> None:
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.content = b'{"valid":true,"diagnostics":[],"durationMicros":42}'
        response.json.return_value = {"valid": True, "diagnostics": [], "durationMicros": 42}
        request.return_value = response

        result = LanguageServiceClient().validate(12, 34, "SELECT 1")

        request.assert_called_once()
        call = request.call_args
        assert call.args == ("POST", "http://language-service:8091/teams/12/users/34/validate")
        assert call.kwargs["json"] == {"query": "SELECT 1"}
        assert call.kwargs["timeout"] == (0.25, 1)
        token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = decode_jwt(
            token,
            PosthogJwtAudience.HOGQL_LANGUAGE_SERVICE,
            verification_keys=["test-language-service-signing-key"],
        )
        assert claims["team_id"] == 12
        assert claims["user_id"] == 34
        assert claims["operations"] == ["validate"]
        assert result.body["valid"] is True
        assert result.response_size_bytes == len(response.content)

    @patch("posthog.hogql.language_service.requests.request")
    def test_catalog_miss_has_a_distinct_error(self, request: MagicMock) -> None:
        response = MagicMock()
        response.ok = False
        response.status_code = 404
        response.content = b"catalog not found"
        request.return_value = response

        with self.assertRaises(CatalogMissing):
            LanguageServiceClient().autocomplete(12, 34, "SELECT ", 7)


class TestLanguageServiceFeatureFlag(SimpleTestCase):
    @override_settings(DEBUG=True, HOGQL_LANGUAGE_SERVICE_URL="", HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=[])
    def test_disabled_without_service_configuration(self) -> None:
        assert not is_language_service_enabled(MagicMock(), MagicMock())

    @override_settings(
        DEBUG=True,
        HOGQL_LANGUAGE_SERVICE_URL="http://language-service:8091",
        HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=["key"],
    )
    def test_enabled_in_debug_with_service_configuration(self) -> None:
        assert is_language_service_enabled(MagicMock(), MagicMock())

    @override_settings(
        DEBUG=False,
        HOGQL_LANGUAGE_SERVICE_URL="http://language-service:8091",
        HOGQL_LANGUAGE_SERVICE_SIGNING_KEYS=["key"],
    )
    @patch("posthog.hogql.language_service.posthoganalytics.feature_enabled", return_value=True)
    def test_production_uses_local_feature_flag_evaluation(self, feature_enabled: MagicMock) -> None:
        team = MagicMock(id=12, organization_id=56)
        user = MagicMock(distinct_id="user-distinct-id")

        assert is_language_service_enabled(team, user)
        feature_enabled.assert_called_once_with(
            "hogql-language-service",
            "user-distinct-id",
            groups={"organization": "56", "project": "12"},
            group_properties={"organization": {"id": "56"}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
