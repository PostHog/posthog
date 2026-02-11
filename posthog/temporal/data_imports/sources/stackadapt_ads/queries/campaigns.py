CAMPAIGNS_QUERY = """
query GetCampaigns($first: Int!, $after: String) {
    campaigns(first: $first, after: $after) {
        nodes {
            id
            name
            state
            type
            budgetRollover
            isArchived
            isDraft
            createdAt
            updatedAt
            advertiser {
                id
                name
            }
            campaignGroup {
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
