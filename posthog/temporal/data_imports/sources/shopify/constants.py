from .queries.abandoned_checkouts import ABANDONED_CHECKOUTS_QUERY
from .queries.articles import ARTICLES_QUERY
from .utils import ShopifyGraphQLObject

SHOPIFY_API_VERSION = "2025-10"
SHOPIFY_API_URL = "https://{}.myshopify.com/admin/api/{}/graphql.json"
SHOPIFY_DEFAULT_PAGE_SIZE = 100

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
SMART_COLLECTIONS = "smartCollections"
TENDER_TRANSACTIONS = "tenderTransactions"
TRANSACTIONS = "transactions"


# NOTE: some of the permissions queries may seem random. not every field on a given graphql object
# have the same access requirements
SHOPIFY_GRAPHQL_OBJECTS = {
    ABANDONED_CHECKOUTS: ShopifyGraphQLObject(
        name=ABANDONED_CHECKOUTS,
        query=ABANDONED_CHECKOUTS_QUERY,
        permissions_query="{ abandonedCheckoutsCount(limit: 1) { count } }",
    ),
    ARTICLES: ShopifyGraphQLObject(
        name=ARTICLES,
        query=ARTICLES_QUERY,
        permissions_query="{ articles(first: 1) { nodes { commentsCount(limit: 1) { count } } } }",
    ),
    # BLOGS: ShopifyGraphQLObject(name=BLOGS, query=""),
    # COLLECTIONS: ShopifyGraphQLObject(name=COLLECTIONS, query=""),
    # COLLECTS: ShopifyGraphQLObject(name=COLLECTS, query=""),
    # COUNTRIES: ShopifyGraphQLObject(name=COUNTRIES, query=""),
    # CUSTOM_COLLECTIONS: ShopifyGraphQLObject(name=CUSTOM_COLLECTIONS, query=""),
    # CUSTOMER_ADDRESS: ShopifyGraphQLObject(name=CUSTOMER_ADDRESS, query=""),
    # CUSTOMER_JOURNEY_SUMMARY: ShopifyGraphQLObject(name=CUSTOMER_JOURNEY_SUMMARY, query=""),
    # CUSTOMERS: ShopifyGraphQLObject(name=CUSTOMERS, query=""),
    # DISCOUNT_CODES: ShopifyGraphQLObject(name=DISCOUNT_CODES, query=""),
    # DISPUTES: ShopifyGraphQLObject(name=DISPUTES, query=""),
    # DRAFT_ORDERS: ShopifyGraphQLObject(name=DRAFT_ORDERS, query=""),
    # FULFILLMENT_ORDERS: ShopifyGraphQLObject(name=FULFILLMENT_ORDERS, query=""),
    # FULFILLMENTS: ShopifyGraphQLObject(name=FULFILLMENTS, query=""),
    # INVENTORY_ITEMS: ShopifyGraphQLObject(name=INVENTORY_ITEMS, query=""),
    # INVENTORY_LEVELS: ShopifyGraphQLObject(name=INVENTORY_LEVELS, query=""),
    # LOCATIONS: ShopifyGraphQLObject(name=LOCATIONS, query=""),
    # METAFIELD_ARTICLES: ShopifyGraphQLObject(name=METAFIELD_ARTICLES, query=""),
    # METAFIELD_BLOGS: ShopifyGraphQLObject(name=METAFIELD_BLOGS, query=""),
    # METAFIELD_COLLECTIONS: ShopifyGraphQLObject(name=METAFIELD_COLLECTIONS, query=""),
    # METAFIELD_CUSTOMERS: ShopifyGraphQLObject(name=METAFIELD_CUSTOMERS, query=""),
    # METAFIELD_DRAFT_ORDERS: ShopifyGraphQLObject(name=METAFIELD_DRAFT_ORDERS, query=""),
    # METAFIELD_LOCATIONS: ShopifyGraphQLObject(name=METAFIELD_LOCATIONS, query=""),
    # METAFIELD_ORDERS: ShopifyGraphQLObject(name=METAFIELD_ORDERS, query=""),
    # METAFIELD_PAGES: ShopifyGraphQLObject(name=METAFIELD_PAGES, query=""),
    # METAFIELD_PRODUCT_IMAGES: ShopifyGraphQLObject(name=METAFIELD_PRODUCT_IMAGES, query=""),
    # METAFIELD_PRODUCT_VARIANTS: ShopifyGraphQLObject(name=METAFIELD_PRODUCT_VARIANTS, query=""),
    # METAFIELD_PRODUCTS: ShopifyGraphQLObject(name=METAFIELD_PRODUCTS, query=""),
    # METAFIELD_SHOPS: ShopifyGraphQLObject(name=METAFIELD_SHOPS, query=""),
    # METAFIELD_SMART_COLLECTIONS: ShopifyGraphQLObject(name=METAFIELD_SMART_COLLECTIONS, query=""),
    # ORDER_AGREEMENTS: ShopifyGraphQLObject(name=ORDER_AGREEMENTS, query=""),
    # ORDER_REFUNDS: ShopifyGraphQLObject(name=ORDER_REFUNDS, query=""),
    # ORDER_RISKS: ShopifyGraphQLObject(name=ORDER_RISKS, query=""),
    # ORDERS: ShopifyGraphQLObject(name=ORDERS, query=""),
    # PAGES: ShopifyGraphQLObject(name=PAGES, query=""),
    # PRICE_RULES: ShopifyGraphQLObject(name=PRICE_RULES, query=""),
    # PRODUCT_IMAGES: ShopifyGraphQLObject(name=PRODUCT_IMAGES, query=""),
    # PRODUCT_VARIANTS: ShopifyGraphQLObject(name=PRODUCT_VARIANTS, query=""),
    # PRODUCTS: ShopifyGraphQLObject(name=PRODUCTS, query=""),
    # PROFILE_LOCATION_GROUPS: ShopifyGraphQLObject(name=PROFILE_LOCATION_GROUPS, query=""),
    # SHOP: ShopifyGraphQLObject(name=SHOP, query=""),
    # SMART_COLLECTIONS: ShopifyGraphQLObject(name=SMART_COLLECTIONS, query=""),
    # TENDER_TRANSACTIONS: ShopifyGraphQLObject(name=TENDER_TRANSACTIONS, query=""),
    # TRANSACTIONS: ShopifyGraphQLObject(name=TRANSACTIONS, query=""),
}
