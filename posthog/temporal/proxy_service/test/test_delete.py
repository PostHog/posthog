import uuid

from unittest.mock import patch

from posthog.temporal.proxy_service.delete import DeleteManagedProxyInputs, delete_cloudflare_proxy


class TestDeleteCloudflareProxy:
    @patch("posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect")
    @patch("posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain", return_value=None)
    async def test_clears_kv_even_when_no_root_redirect_is_configured(self, _get_hostname, update_redirect):
        inputs = DeleteManagedProxyInputs(
            organization_id=uuid.uuid4(),
            proxy_record_id=uuid.uuid4(),
            domain="test.example.com",
            root_redirect_url=None,
        )

        await delete_cloudflare_proxy(inputs)

        update_redirect.assert_called_once_with("test.example.com", None)
