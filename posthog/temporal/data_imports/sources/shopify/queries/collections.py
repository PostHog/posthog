from posthog.temporal.data_imports.sources.shopify.queries.fragments import (
    COUNT_FRAGMENT,
    METAFIELD_CONNECTIONS_FRAGMENT,
    NODE_CONNECTION_ID_FRAGMENT,
)

COLLECTIONS_SORTKEY = "UPDATED_AT"

# 250 is the maximum value for first. including metafields is a best effort since they
# are customized key value pairs
COLLECTIONS_QUERY = f"""
query PaginatedCollections($pageSize: Int!, $cursor: String, $query: String) {{
    collections(
        first: $pageSize, after: $cursor, sortKey: {COLLECTIONS_SORTKEY},
        query: $query
    ) {{
        nodes {{
            availablePublicationsCount {COUNT_FRAGMENT}
            description
            descriptionHtml
            feedback {{
                details {{
                    feedbackGeneratedAt
                    link {{
                       label
                       url
                    }}
                    messages {{
                        field
                        message
                    }}
                    state
                }}
                summary
            }}
            handle
            id
            metafields(first: 250) {METAFIELD_CONNECTIONS_FRAGMENT}
            products(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
            productsCount {COUNT_FRAGMENT}
            ruleSet {{
                appliedDisjunctively
                rules {{
                    column
                    condition
                    relation
                }}
            }}
            seo {{
                description
                title
            }}
            sortOrder
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
