from posthog.temporal.data_imports.sources.shopify.queries.fragments import (
    COUNT_FRAGMENT,
    METAFIELD_CONNECTIONS_FRAGMENT,
)

BLOGS_SORTKEY = "ID"

# 250 is the maximum value for first. including metafields is a best effort since they
# are customized key value pairs
BLOGS_QUERY = f"""
query PaginatedBlogs($pageSize: Int!, $cursor: String, $query: String) {{
    blogs(
        first: $pageSize, after: $cursor, sortKey: {BLOGS_SORTKEY},
        query: $query
    ) {{
        nodes {{
            articlesCount {COUNT_FRAGMENT}
            createdAt
            handle
            id
            metafields(first: 250) {METAFIELD_CONNECTIONS_FRAGMENT}
            tags
            templateSuffix
            title
            updatedAt
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
