from posthog.temporal.data_imports.sources.common.graphql_source.typing import GraphQLResource

from .graphql.abandoned_checkouts import ABANDONED_CHECKOUTS_QUERY
from .graphql.articles import ARTICLES_QUERY
from .graphql.shopify_payments_balance_transactions import SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS_QUERY

SHOPIFY_API_VERSION = "2025-10"
SHOPIFY_API_URL = "{store_url}/admin/api/{api_version}/graphql.json"

SHOPIFY_ACCESS_TOKEN_CHECK = "{ shop { id } }"

ABANDONED_CHECKOUTS = "AbandonedCheckouts"
ARTICLES = "Articles"
BLOGS = "Blogs"
COLLECTIONS = "Collections"
COLLECTS = "Collects"
COUNTRIES = "Countries"
CUSTOM_COLLECTIONS = "CustomCollections"
CUSTOMER_ADDRESS = "CustomerAddress"
CUSTOMER_JOURNEY_SUMMARY = "CustomerJourneySummary"
CUSTOMERS = "Customers"
DISCOUNT_CODES = "DiscountCodes"
DISPUTES = "Disputes"
DRAFT_ORDERS = "DraftOrders"
FULFILLMENT_ORDERS = "FulfillmentOrders"
FULFILLMENTS = "Fulfillments"
INVENTORY_ITEMS = "InventoryItems"
INVENTORY_LEVELS = "InventoryLevels"
LOCATIONS = "Locations"
METAFIELD_ARTICLES = "MetafieldArticles"
METAFIELD_BLOGS = "MetafieldBlogs"
METAFIELD_COLLECTIONS = "MetafieldCollections"
METAFIELD_CUSTOMERS = "MetafieldCustomers"
METAFIELD_DRAFT_ORDERS = "MetafieldDraftOrders"
METAFIELD_LOCATIONS = "MetafieldLocations"
METAFIELD_ORDERS = "MetafieldOrders"
METAFIELD_PAGES = "MetafieldPages"
METAFIELD_PRODUCT_IMAGES = "MetafieldProductImages"
METAFIELD_PRODUCT_VARIANTS = "MetafieldProductVariants"
METAFIELD_PRODUCTS = "MetafieldProducts"
METAFIELD_SHOPS = "MetafieldShops"
METAFIELD_SMART_COLLECTIONS = "MetafieldSmartCollections"
ORDER_AGREEMENTS = "OrderAgreements"
ORDER_REFUNDS = "OrderRefunds"
ORDER_RISKS = "OrderRisks"
ORDERS = "Orders"
PAGES = "Pages"
PRICE_RULES = "PriceRules"
PRODUCT_IMAGES = "ProductImages"
PRODUCT_VARIANTS = "ProductVariants"
PRODUCTS = "Products"
PROFILE_LOCATION_GROUPS = "ProfileLocationGroups"
SHOP = "Shop"
SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS = "ShopifyPaymentsBalanceTransactions"
SMART_COLLECTIONS = "SmartCollections"
TENDER_TRANSACTIONS = "TenderTransactions"
TRANSACTIONS = "Transactions"


# NOTE: some of the permissions queries may seem random. not every field on a given resource
# have the same access requirements
SHOPIFY_RESOURCES = {
    ABANDONED_CHECKOUTS: GraphQLResource(
        name=ABANDONED_CHECKOUTS,
        query=ABANDONED_CHECKOUTS_QUERY,
        permissions_query="{ abandonedCheckoutsCount(limit: 1) { count } }",
    ),
    ARTICLES: GraphQLResource(
        name=ARTICLES,
        query=ARTICLES_QUERY,
        permissions_query="{ articles(first: 1) { nodes { commentsCount(limit: 1) { count } } } }",
    ),
    # BLOGS: GraphQLResource(name=BLOGS, query=""),
    # COLLECTIONS: GraphQLResource(name=COLLECTIONS, query=""),
    # COLLECTS: GraphQLResource(name=COLLECTS, query=""),
    # COUNTRIES: GraphQLResource(name=COUNTRIES, query=""),
    # CUSTOM_COLLECTIONS: GraphQLResource(name=CUSTOM_COLLECTIONS, query=""),
    # CUSTOMER_ADDRESS: GraphQLResource(name=CUSTOMER_ADDRESS, query=""),
    # CUSTOMER_JOURNEY_SUMMARY: GraphQLResource(name=CUSTOMER_JOURNEY_SUMMARY, query=""),
    # CUSTOMERS: GraphQLResource(name=CUSTOMERS, query=""),
    # DISCOUNT_CODES: GraphQLResource(name=DISCOUNT_CODES, query=""),
    # DISPUTES: GraphQLResource(name=DISPUTES, query=""),
    # DRAFT_ORDERS: GraphQLResource(name=DRAFT_ORDERS, query=""),
    # FULFILLMENT_ORDERS: GraphQLResource(name=FULFILLMENT_ORDERS, query=""),
    # FULFILLMENTS: GraphQLResource(name=FULFILLMENTS, query=""),
    # INVENTORY_ITEMS: GraphQLResource(name=INVENTORY_ITEMS, query=""),
    # INVENTORY_LEVELS: GraphQLResource(name=INVENTORY_LEVELS, query=""),
    # LOCATIONS: GraphQLResource(name=LOCATIONS, query=""),
    # METAFIELD_ARTICLES: GraphQLResource(name=METAFIELD_ARTICLES, query=""),
    # METAFIELD_BLOGS: GraphQLResource(name=METAFIELD_BLOGS, query=""),
    # METAFIELD_COLLECTIONS: GraphQLResource(name=METAFIELD_COLLECTIONS, query=""),
    # METAFIELD_CUSTOMERS: GraphQLResource(name=METAFIELD_CUSTOMERS, query=""),
    # METAFIELD_DRAFT_ORDERS: GraphQLResource(name=METAFIELD_DRAFT_ORDERS, query=""),
    # METAFIELD_LOCATIONS: GraphQLResource(name=METAFIELD_LOCATIONS, query=""),
    # METAFIELD_ORDERS: GraphQLResource(name=METAFIELD_ORDERS, query=""),
    # METAFIELD_PAGES: GraphQLResource(name=METAFIELD_PAGES, query=""),
    # METAFIELD_PRODUCT_IMAGES: GraphQLResource(name=METAFIELD_PRODUCT_IMAGES, query=""),
    # METAFIELD_PRODUCT_VARIANTS: GraphQLResource(name=METAFIELD_PRODUCT_VARIANTS, query=""),
    # METAFIELD_PRODUCTS: GraphQLResource(name=METAFIELD_PRODUCTS, query=""),
    # METAFIELD_SHOPS: GraphQLResource(name=METAFIELD_SHOPS, query=""),
    # METAFIELD_SMART_COLLECTIONS: GraphQLResource(name=METAFIELD_SMART_COLLECTIONS, query=""),
    # ORDER_AGREEMENTS: GraphQLResource(name=ORDER_AGREEMENTS, query=""),
    # ORDER_REFUNDS: GraphQLResource(name=ORDER_REFUNDS, query=""),
    # ORDER_RISKS: GraphQLResource(name=ORDER_RISKS, query=""),
    # ORDERS: GraphQLResource(name=ORDERS, query=""),
    # PAGES: GraphQLResource(name=PAGES, query=""),
    # PRICE_RULES: GraphQLResource(name=PRICE_RULES, query=""),
    # PRODUCT_IMAGES: GraphQLResource(name=PRODUCT_IMAGES, query=""),
    # PRODUCT_VARIANTS: GraphQLResource(name=PRODUCT_VARIANTS, query=""),
    # PRODUCTS: GraphQLResource(name=PRODUCTS, query=""),
    # PROFILE_LOCATION_GROUPS: GraphQLResource(name=PROFILE_LOCATION_GROUPS, query=""),
    # SHOP: GraphQLResource(name=SHOP, query=""),
    SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS: GraphQLResource(
        name=SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS,
        query=SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS_QUERY,
        permissions_query="{ shop { id } }",
    ),
    # SMART_COLLECTIONS: GraphQLResource(name=SMART_COLLECTIONS, query=""),
    # TENDER_TRANSACTIONS: GraphQLResource(name=TENDER_TRANSACTIONS, query=""),
    # TRANSACTIONS: GraphQLResource(name=TRANSACTIONS, query=""),
}
