"""Canonical, documentation-sourced descriptions for Shopify endpoints and columns.

Sourced from the official Shopify Admin GraphQL API reference (https://shopify.dev/docs/api/admin-graphql).
Keyed by the schema names that `get_schemas` returns (the GraphQL object's `display_name or name`
from `constants.py` `SHOPIFY_GRAPHQL_OBJECTS`), which match the `ExternalDataSchema.name` of a synced
Shopify table. Columns absent here fall back to LLM enrichment.
"""

from posthog.temporal.data_imports.sources.common.canonical_descriptions import CanonicalDescriptions

# Fields shared by most Shopify GraphQL objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Globally unique identifier for the object (a Shopify GraphQL GID).",
    "created_at": "Date and time when the object was created.",
    "updated_at": "Date and time when the object was last updated.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "abandonedCheckouts": {
        "description": "A checkout a customer started but did not complete, leaving items in their cart.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/AbandonedCheckout",
        "columns": _columns(
            abandonedCheckoutUrl="URL the customer can use to recover and complete the abandoned checkout.",
            totalPriceSet="Total price of the checkout, in shop and presentment currencies.",
            subtotalPriceSet="Subtotal of the line items before taxes and shipping.",
            totalTaxSet="Total tax charged on the checkout.",
            lineItems="The products and quantities the customer added to the abandoned checkout.",
            customer="The customer associated with the abandoned checkout.",
            completedAt="Date and time when the checkout was completed, if it ever was.",
        ),
    },
    "articles": {
        "description": "A blog post (article) published to one of the shop's online store blogs.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Article",
        "columns": _columns(
            title="The article's title.",
            handle="URL-friendly unique handle for the article.",
            body="The article's content, in HTML.",
            summary="Short summary of the article.",
            author="The author of the article.",
            blog="The blog the article belongs to.",
            tags="List of tags applied to the article.",
            isPublished="Whether the article is visible on the online store.",
            publishedAt="Date and time when the article was published.",
        ),
    },
    "blogs": {
        "description": "A blog on the shop's online store that groups together articles.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Blog",
        "columns": _columns(
            title="The blog's title.",
            handle="URL-friendly unique handle for the blog.",
            tags="List of tags used across the blog's articles.",
        ),
    },
    "catalogs": {
        "description": "A catalog that maps a set of products and prices to a market, company location, or app.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/interfaces/Catalog",
        "columns": _columns(
            title="The catalog's title.",
            status="Status of the catalog (e.g. ACTIVE, ARCHIVED, DRAFT).",
            priceList="The price list associated with the catalog.",
        ),
    },
    "collections": {
        "description": "A grouping of products that can be displayed and merchandised together in the store.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Collection",
        "columns": _columns(
            title="The collection's title.",
            handle="URL-friendly unique handle for the collection.",
            description="The collection's description, as plain text.",
            descriptionHtml="The collection's description, in HTML.",
            productsCount="Number of products in the collection.",
            sortOrder="The order in which products in the collection are displayed.",
            updatedAt="Date and time when the collection was last modified.",
        ),
    },
    "customers": {
        "description": "A customer of the shop, holding contact details and order history.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Customer",
        "columns": _columns(
            firstName="The customer's first name.",
            lastName="The customer's last name.",
            displayName="The customer's full name, formatted for display.",
            email="The customer's email address.",
            phone="The customer's phone number, in E.164 format.",
            numberOfOrders="Number of orders the customer has placed.",
            amountSpent="Total amount the customer has spent across all orders.",
            state="The customer's account state (e.g. ENABLED, DISABLED, INVITED, DECLINED).",
            verifiedEmail="Whether the customer has verified their email address.",
            tags="List of tags applied to the customer.",
            defaultAddress="The customer's default mailing address.",
            note="Free-form note attached to the customer.",
        ),
    },
    "discountCodes": {
        "description": "A discount and its application rules — a code or automatic discount applied at checkout.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/DiscountNode",
        "columns": _columns(
            discount="The underlying discount object, with its type, value, and eligibility rules.",
        ),
    },
    "orders": {
        "description": "A customer's completed request to purchase one or more products from the shop.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Order",
        "columns": _columns(
            name="The order's identifier, shown to the merchant and customer (e.g. #1001).",
            email="Email address associated with the order.",
            phone="Phone number associated with the order.",
            customer="The customer who placed the order.",
            displayFinancialStatus="Financial status of the order (e.g. PAID, PENDING, REFUNDED, VOIDED).",
            displayFulfillmentStatus="Fulfillment status of the order (e.g. FULFILLED, UNFULFILLED, PARTIALLY_FULFILLED).",
            currentTotalPriceSet="Current total price of the order, in shop and presentment currencies.",
            totalPriceSet="Total price of the order at the time it was placed.",
            subtotalPriceSet="Sum of line item prices before taxes, shipping, and discounts.",
            totalTaxSet="Total tax charged on the order.",
            totalDiscountsSet="Total value of discounts applied to the order.",
            lineItems="The products and quantities purchased in the order.",
            shippingAddress="The address the order is shipped to.",
            billingAddress="The address used for billing.",
            cancelledAt="Date and time when the order was cancelled, if it was.",
            cancelReason="Reason the order was cancelled, if applicable.",
            test="Whether the order is a test order.",
            tags="List of tags applied to the order.",
        ),
    },
    "products": {
        "description": "A product the shop sells, grouping its variants, media, and selling details.",
        "docs_url": "https://shopify.dev/docs/api/admin-graphql/latest/objects/Product",
        "columns": _columns(
            title="The product's title.",
            handle="URL-friendly unique handle for the product.",
            description="The product's description, as plain text.",
            descriptionHtml="The product's description, in HTML.",
            productType="The merchant-defined type of the product.",
            vendor="The product's vendor.",
            status="The product's status (ACTIVE, ARCHIVED, or DRAFT).",
            tags="List of tags applied to the product.",
            totalInventory="Total quantity of the product in stock across all variants.",
            variants="The product's variants (combinations of options like size and color).",
            publishedAt="Date and time when the product was published to the online store.",
        ),
    },
}
