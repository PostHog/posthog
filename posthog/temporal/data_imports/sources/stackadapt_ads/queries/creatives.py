CREATIVES_QUERY = """
query GetCreatives($first: Int!, $after: String) {
    creatives(first: $first, after: $after) {
        nodes {
            id
            name
            type
            state
            clickUrl
            imageUrl
            videoUrl
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
