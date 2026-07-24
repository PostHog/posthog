from decimal import Decimal

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from products.conversations.backend.services.merch_code import (
    MerchCodeError,
    MerchCodeNotConfigured,
    create_merch_code,
    derive_merch_code,
)

MOCK_TARGET = "products.conversations.backend.services.merch_code.shopify_request"


def _ok_response(body: dict) -> MagicMock:
    return MagicMock(ok=True, json=MagicMock(return_value=body))


def _success_body(discount_id: str | None = "gid://shopify/DiscountCodeNode/987") -> dict:
    node = {"id": discount_id} if discount_id is not None else None
    return {"data": {"discountCodeBasicCreate": {"codeDiscountNode": node, "userErrors": []}}}


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
    @patch(MOCK_TARGET)
    def test_success_builds_request_and_parses_response(self, mock_request: MagicMock) -> None:
        mock_request.return_value = _ok_response(_success_body())
        result = create_merch_code(context="ticket-42", value_usd=Decimal("50"), usage_limit=3)

        assert len(result["code"]) == 12
        assert result["discount_url"] == f"https://shop.posthog.com/discount/{result['code']}"
        assert result["admin_url"] == "https://admin.shopify.com/store/posthog/discounts/987"

        sent = mock_request.call_args.kwargs["json"]["variables"]["input"]
        assert sent["customerGets"]["value"]["discountAmount"]["amount"] == "50.00"
        assert sent["usageLimit"] == 3

    @override_settings(
        SHOPIFY_MERCH_ACCESS_TOKEN="tok",
        SHOPIFY_MERCH_HASH_KEY="salt",
        SHOPIFY_MERCH_STORE_DOMAIN="posthog-staging.myshopify.com",
    )
    @patch(MOCK_TARGET)
    def test_admin_url_follows_configured_store(self, mock_request: MagicMock) -> None:
        # The admin link must track SHOPIFY_MERCH_STORE_DOMAIN, not a hardcoded slug, or staff on a
        # non-default store get sent to the wrong admin panel.
        mock_request.return_value = _ok_response(_success_body("gid://shopify/DiscountCodeNode/55"))
        result = create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)
        assert result["admin_url"] == "https://admin.shopify.com/store/posthog-staging/discounts/55"

    @override_settings(SHOPIFY_MERCH_ACCESS_TOKEN="tok", SHOPIFY_MERCH_HASH_KEY="salt")
    @patch(MOCK_TARGET)
    def test_fails_closed_when_no_discount_node(self, mock_request: MagicMock) -> None:
        # No errors but no codeDiscountNode means Shopify never created the discount; returning the
        # locally-derived code anyway would hand the customer a code that does not exist.
        mock_request.return_value = _ok_response(_success_body(discount_id=None))
        with self.assertRaises(MerchCodeError):
            create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)

    @override_settings(SHOPIFY_MERCH_ACCESS_TOKEN="tok", SHOPIFY_MERCH_HASH_KEY="salt")
    @patch(MOCK_TARGET)
    def test_raises_on_non_2xx(self, mock_request: MagicMock) -> None:
        mock_request.return_value = MagicMock(ok=False, status_code=401, text="Unauthorized")
        with self.assertRaises(MerchCodeError):
            create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)

    @override_settings(SHOPIFY_MERCH_ACCESS_TOKEN="tok", SHOPIFY_MERCH_HASH_KEY="salt")
    @patch(MOCK_TARGET)
    def test_raises_on_non_json_response(self, mock_request: MagicMock) -> None:
        # A 200 with an HTML body (e.g. an edge proxy) must fail as MerchCodeError, not a raw 500.
        mock_request.return_value = MagicMock(ok=True, json=MagicMock(side_effect=ValueError("no json")))
        with self.assertRaises(MerchCodeError):
            create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)

    @override_settings(SHOPIFY_MERCH_ACCESS_TOKEN="tok", SHOPIFY_MERCH_HASH_KEY="salt")
    @patch(MOCK_TARGET)
    def test_raises_on_shopify_user_errors(self, mock_request: MagicMock) -> None:
        body = {
            "data": {
                "discountCodeBasicCreate": {
                    "codeDiscountNode": None,
                    "userErrors": [{"field": "code", "message": "Code already exists", "code": "TAKEN"}],
                }
            }
        }
        mock_request.return_value = _ok_response(body)
        with self.assertRaises(MerchCodeError):
            create_merch_code(context="ticket-1", value_usd=Decimal("30"), usage_limit=1)
