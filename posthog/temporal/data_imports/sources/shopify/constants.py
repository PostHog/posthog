from posthog.temporal.data_imports.sources.common.graphql_source.typing import GraphQLResource

from .graphql.abandoned_checkouts import ABANDONED_CHECKOUTS_QUERY
from .graphql.articles import ARTICLES_QUERY
from .graphql.shopify_payments_balance_transactions import SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS_QUERY

SHOPIFY_API_VERSION = "2025-10"
SHOPIFY_API_URL = "https://{}.myshopify.com/admin/api/{}/graphql.json"

SHOPIFY_ACCESS_TOKEN_CHECK = "{ shop { id } }"

ABANDONED_CHECKOUTS = "abandonedCheckouts"
ARTICLES = "articles"
BLOGS = "blogs"
COLLECTIONS = "collections"
COLLECTS = "collects"
COUNTRIES = "countries"
CUSTOM_COLLECTIONS = "customCollections"
CUSTOMER_ADDRESS = "customerAddress"
CUSTOMER_JOURNEY_SUMMARY = "customerJourneySummary"
CUSTOMERS = "customers"
DISCOUNT_CODES = "discountCodes"
DISPUTES = "disputes"
DRAFT_ORDERS = "draftOrders"
FULFILLMENT_ORDERS = "fulfillmentOrders"
FULFILLMENTS = "fulfillments"
INVENTORY_ITEMS = "inventoryItems"
INVENTORY_LEVELS = "inventoryLevels"
LOCATIONS = "locations"
METAFIELD_ARTICLES = "metafieldArticles"
METAFIELD_BLOGS = "metafieldBlogs"
METAFIELD_COLLECTIONS = "metafieldCollections"
METAFIELD_CUSTOMERS = "metafieldCustomers"
METAFIELD_DRAFT_ORDERS = "metafieldDraftOrders"
METAFIELD_LOCATIONS = "metafieldLocations"
METAFIELD_ORDERS = "metafieldOrders"
METAFIELD_PAGES = "metafieldPages"
METAFIELD_PRODUCT_IMAGES = "metafieldProductImages"
METAFIELD_PRODUCT_VARIANTS = "metafieldProductVariants"
METAFIELD_PRODUCTS = "metafieldProducts"
METAFIELD_SHOPS = "metafieldShops"
METAFIELD_SMART_COLLECTIONS = "metafieldSmartCollections"
ORDER_AGREEMENTS = "orderAgreements"
ORDER_REFUNDS = "orderRefunds"
ORDER_RISKS = "orderRisks"
ORDERS = "orders"
PAGES = "pages"
PRICE_RULES = "priceRules"
PRODUCT_IMAGES = "productImages"
PRODUCT_VARIANTS = "productVariants"
PRODUCTS = "products"
PROFILE_LOCATION_GROUPS = "profileLocationGroups"
SHOP = "shop"
SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS = "shopifyPaymentsBalanceTransactions"
SMART_COLLECTIONS = "smartCollections"
TENDER_TRANSACTIONS = "tenderTransactions"
TRANSACTIONS = "transactions"


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
        accessor="data.shopifyPaymentsAccount.balanceTransactions",
    ),
    # SMART_COLLECTIONS: GraphQLResource(name=SMART_COLLECTIONS, query=""),
    # TENDER_TRANSACTIONS: GraphQLResource(name=TENDER_TRANSACTIONS, query=""),
    # TRANSACTIONS: GraphQLResource(name=TRANSACTIONS, query=""),
}
