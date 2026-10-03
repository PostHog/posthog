from posthog.test.clickhouse_free import ClickhouseFreeSimpleTestCase

from products.ai_observability.backend.llm.config import ProviderConfig


class TestProviderConfig(ClickhouseFreeSimpleTestCase):
    def test_provider_config_immutable(self):
        config = ProviderConfig(api_key="test-key", base_url="https://example.com")
        assert config.api_key == "test-key"
        assert config.base_url == "https://example.com"

    def test_provider_config_default_base_url(self):
        config = ProviderConfig(api_key="test-key")
        assert config.base_url is None
