CONVERSION_TRACKERS_QUERY = """
query GetConversionTrackers($first: Int!, $after: String) {
    conversionTrackers(first: $first, after: $after) {
        nodes {
            id
            name
            type
            countType
            createdAt
            updatedAt
            advertiser {
                id
                name
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}
"""
