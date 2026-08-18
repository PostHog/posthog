from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from ee.hogai.utils.feature_flags import is_web_search_available


class TestIsWebSearchAvailable(BaseTest):
    @parameterized.expand(
        [
            ("control", "control", True),
            ("anthropic_primary", "gateway-anthropic", True),
            ("bedrock_primary", "gateway-bedrock", False),
        ]
    )
    def test_availability_by_variant_when_gateway_configured(self, _name, variant, expected):
        with (
            patch("ee.hogai.utils.feature_flags.get_llm_gateway_variant", return_value=variant),
            patch("ee.hogai.utils.feature_flags.settings") as mock_settings,
        ):
            mock_settings.LLM_GATEWAY_URL = "http://gateway:3308"
            mock_settings.LLM_GATEWAY_API_KEY = "test-key"
            self.assertIs(is_web_search_available(self.team, self.user), expected)

    def test_available_for_bedrock_when_gateway_not_configured(self):
        # Without a gateway URL/key the request can't route to Bedrock, so web search stays offered.
        with (
            patch("ee.hogai.utils.feature_flags.get_llm_gateway_variant", return_value="gateway-bedrock"),
            patch("ee.hogai.utils.feature_flags.settings") as mock_settings,
        ):
            mock_settings.LLM_GATEWAY_URL = ""
            mock_settings.LLM_GATEWAY_API_KEY = ""
            self.assertIs(is_web_search_available(self.team, self.user), True)
