ARTICLES_QUERY = """
query PaginatedArticles($n: Int!, $cursor: String) {
    articles(first: $n, after: $cursor) {
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
            commentsCount
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
