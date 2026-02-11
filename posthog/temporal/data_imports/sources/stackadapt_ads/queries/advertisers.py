ADVERTISERS_QUERY = """
query GetAdvertisers($first: Int!, $after: String) {
    advertisers(first: $first, after: $after) {
        nodes {
            id
            name
            createdAt
            updatedAt
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}
"""
