from .queries.abandoned_checkouts import ABANDONED_CHECKOUTS_QUERY
from .queries.articles import ARTICLES_QUERY
from .queries.blogs import BLOGS_QUERY
from .queries.catalogs import CATALOGS_QUERY
from .queries.collections import COLLECTIONS_QUERY
from .queries.customers import CUSTOMERS_QUERY
from .queries.discount_nodes import DISCOUNT_NODES_QUERY
from .utils import ShopifyGraphQLObject

SHOPIFY_API_VERSION = "2025-10"
SHOPIFY_API_URL = "https://{}.myshopify.com/admin/api/{}/graphql.json"
SHOPIFY_DEFAULT_PAGE_SIZE = 100

SHOPIFY_ACCESS_TOKEN_CHECK = "{ shop { id } }"


ID = "id"
CREATED_AT = "created_at"
UPDATED_AT = "updated_at"

ABANDONED_CHECKOUTS = "abandonedCheckouts"
ARTICLES = "articles"
BLOGS = "blogs"
CATALOGS = "catalogs"
COLLECTIONS = "collections"
CUSTOMERS = "customers"
DISCOUNT_NODES = "discountNodes"
DISPUTES = "disputes"
DRAFT_ORDERS = "draftOrders"
INVENTORY_ITEMS = "inventoryItems"
LOCATIONS = "locations"
METAFIELD_DEFINITIONS = "metafieldDefinitions"
ORDERS = "orders"
PAGES = "pages"
PRODUCTS = "products"
SHOP = "shop"
SUBSCRIPTION_CONTRACTS = "subscriptionContracts"


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
    BLOGS: ShopifyGraphQLObject(
        name=BLOGS,
        query=BLOGS_QUERY,
        permissions_query="{ blogs(first: 1) { nodes { articlesCount(limit: 1) { count } } } }",
    ),
    CATALOGS: ShopifyGraphQLObject(
        name=CATALOGS,
        query=CATALOGS_QUERY,
        permissions_query="{ catalogs(first: 1) { nodes { id } } }",
    ),
    COLLECTIONS: ShopifyGraphQLObject(
        name=COLLECTIONS,
        query=COLLECTIONS_QUERY,
        permissions_query="{ collections(first: 1) { nodes { availablePublicationsCount { count } } } }",
    ),
    CUSTOMERS: ShopifyGraphQLObject(
        name=CUSTOMERS,
        query=CUSTOMERS_QUERY,
        permissions_query="{ customers(first: 1) { nodes { id } } }",
    ),
    DISCOUNT_NODES: ShopifyGraphQLObject(
        name=DISCOUNT_NODES,
        query=DISCOUNT_NODES_QUERY,
        display_name="discountCodes",
        permissions_query="{ discountNodes(first: 1) { nodes { id } } }",
    ),
}


def resolve_schema_name(name: str):
    for obj in SHOPIFY_GRAPHQL_OBJECTS.values():
        if name == obj.display_name:
            return obj.name
    return name
