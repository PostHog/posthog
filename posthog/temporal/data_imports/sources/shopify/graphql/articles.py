ARTICLES_QUERY = """
query PaginatedArticles($pageSize: Int!, $cursor: String) {
    articles(first: $pageSize, after: $cursor) {
        nodes {
            author {
                name
            }
            blog {
                handle
                id
                tags
                title
            }
            body
            commentsCount(limit: null) {
                count
            }
            createdAt
            handle
            id
            isPublished
            publishedAt
            summary
            tags
            templateSuffix
            title
            updatedAt
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""
