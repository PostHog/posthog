from decimal import Decimal

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from products.conversations.backend.services.merch_code import (
    MerchCodeError,
    MerchCodeNotConfigured,
    create_merch_code,
    derive_merch_code,
)


class TestMerchCodeService(SimpleTestCase):
    def test_derive_matches_cross_tool_algorithm(self) -> None:
        # Golden vector locks the sha256("{context}-{ts}-{salt}")[:12] contract shared with HogHero/jokerhog;
        # a change here would mint codes that diverge from the other minters.
        assert derive_merch_code("ticket-123", "2026-01-01T00:00:00+00:00", "testsalt") == "bcc9172160f0"

    def test_derive_is_deterministic_and_12_hex_chars(self) -> None:
        code = derive_merch_code("ticket-9", "2026-07-21T00:00:00+00:00", "salt")
        assert code == derive_merch_code("ticket-9", "2026-07-21T00:00:00+00:00", "salt")
        assert len(code) == 12
        assert all(c in "0123456789abcdef" for c in code)

    def test_derive_normalizes_slashes_in_context(self) -> None:
        assert derive_merch_code("a/b", "t", "k") == derive_merch_code("a-b", "t", "k")

    @override_settings(SHOPIFY_MERCH_ACCESS_TOKEN="", SHOPIFY_MERCH_HASH_KEY="")
    def test_raises_when_not_configured(self) -> None:
        with self.assertRaises(MerchCodeNotConfigured):
            create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)

    @override_settings(
        SHOPIFY_MERCH_ACCESS_TOKEN="tok",
        SHOPIFY_MERCH_HASH_KEY="salt",
        SHOPIFY_MERCH_STORE_DOMAIN="posthog.myshopify.com",
        SHOPIFY_MERCH_API_VERSION="2026-04",
    )
    @patch("products.conversations.backend.services.merch_code.requests.post")
    def test_success_builds_request_and_parses_response(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            json=MagicMock(
                return_value={
                    "data": {
                        "discountCodeBasicCreate": {
                            "codeDiscountNode": {"id": "gid://shopify/DiscountCodeNode/987"},
                            "userErrors": [],
                        }
                    }
                }
            )
        )
        result = create_merch_code(context="ticket-42", value_usd=Decimal("50"), usage_limit=3)

        assert len(result["code"]) == 12
        assert result["discount_url"] == f"https://shop.posthog.com/discount/{result['code']}"
        assert result["admin_url"] == "https://admin.shopify.com/store/posthog/discounts/987"

        sent = mock_post.call_args.kwargs["json"]["variables"]["input"]
        assert sent["customerGets"]["value"]["discountAmount"]["amount"] == "50.00"
        assert sent["usageLimit"] == 3

    @override_settings(SHOPIFY_MERCH_ACCESS_TOKEN="tok", SHOPIFY_MERCH_HASH_KEY="salt")
    @patch("products.conversations.backend.services.merch_code.requests.post")
    def test_raises_on_non_json_response(self, mock_post: MagicMock) -> None:
        # Shopify error pages come back as HTML; parsing must fail as MerchCodeError, not a raw 500.
        mock_post.return_value = MagicMock(json=MagicMock(side_effect=ValueError("no json")))
        with self.assertRaises(MerchCodeError):
            create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)

    @override_settings(SHOPIFY_MERCH_ACCESS_TOKEN="tok", SHOPIFY_MERCH_HASH_KEY="salt")
    @patch("products.conversations.backend.services.merch_code.requests.post")
    def test_raises_on_shopify_user_errors(self, mock_post: MagicMock) -> None:
        mock_post.return_value = MagicMock(
            json=MagicMock(
                return_value={
                    "data": {
                        "discountCodeBasicCreate": {
                            "codeDiscountNode": None,
                            "userErrors": [{"field": "code", "message": "Code already exists", "code": "TAKEN"}],
                        }
                    }
                }
            )
        )
        with self.assertRaises(MerchCodeError):
            create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)
