import uuid

import pytest
from unittest.mock import Mock, patch

from posthog.temporal.proxy_service.cloudflare import CloudflareAPIError
from posthog.temporal.proxy_service.common import NonRetriableException
from posthog.temporal.proxy_service.delete import DeleteManagedProxyInputs, delete_cloudflare_proxy


def _inputs(domain: str) -> DeleteManagedProxyInputs:
    return DeleteManagedProxyInputs(
        organization_id=uuid.uuid4(),
        proxy_record_id=uuid.uuid4(),
        domain=domain,
        root_redirect_url=None,
    )


class TestDeleteCloudflareProxy:
    @patch("posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect")
    @patch("posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain", return_value=None)
    async def test_clears_kv_even_when_no_root_redirect_is_configured(self, _get_hostname, update_redirect):
        await delete_cloudflare_proxy(_inputs("test.example.com"))

        update_redirect.assert_called_once_with("test.example.com", None)

    @patch("posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect")
    @patch("posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain")
    async def test_skips_cloudflare_for_a_domain_it_could_never_hold(self, get_hostname, update_redirect):
        await delete_cloudflare_proxy(_inputs("localhost"))

        get_hostname.assert_not_called()
        update_redirect.assert_not_called()

    @patch("posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect")
    @patch(
        "posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain",
        side_effect=CloudflareAPIError("Cloudflare API error: invalid hostname", status_code=400),
    )
    async def test_treats_a_rejected_hostname_as_nothing_to_delete(self, _get_hostname, update_redirect):
        await delete_cloudflare_proxy(_inputs("test.example.com"))

        update_redirect.assert_called_once_with("test.example.com", None)

    @patch("posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect")
    @patch(
        "posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain",
        side_effect=CloudflareAPIError("Cloudflare API error: internal error", status_code=500),
    )
    async def test_still_fails_when_cloudflare_errors(self, _get_hostname, _update_redirect):
        with pytest.raises(NonRetriableException):
            await delete_cloudflare_proxy(_inputs("test.example.com"))

    @patch("posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect")
    @patch(
        "posthog.temporal.proxy_service.delete.delete_custom_hostname",
        side_effect=CloudflareAPIError("Cloudflare API error: bad request", status_code=400),
    )
    @patch(
        "posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain",
        return_value=Mock(id="cf-hostname-id"),
    )
    async def test_fails_when_deleting_a_found_hostname_returns_400(self, _get_hostname, _delete_hostname, _redirect):
        # The lookup found a live hostname, so a 400 from the deletion is a real failure. Dropping
        # the record here would leave the hostname serving traffic with nothing pointing at it.
        with pytest.raises(NonRetriableException):
            await delete_cloudflare_proxy(_inputs("test.example.com"))

    @patch(
        "posthog.temporal.proxy_service.delete.update_cloudflare_proxy_root_redirect",
        side_effect=CloudflareAPIError("Cloudflare API error: bad request", status_code=400),
    )
    @patch("posthog.temporal.proxy_service.delete.get_custom_hostname_by_domain", return_value=None)
    async def test_fails_when_deleting_the_root_redirect_returns_400(self, _get_hostname, _update_redirect):
        # The KV key is real, so a 400 from the redirect delete is a real failure, not a rejected
        # value. Dropping the record here would leave a stale redirect for the domain.
        with pytest.raises(NonRetriableException):
            await delete_cloudflare_proxy(_inputs("test.example.com"))
