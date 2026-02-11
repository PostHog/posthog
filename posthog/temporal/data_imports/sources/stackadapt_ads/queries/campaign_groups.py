CAMPAIGN_GROUPS_QUERY = """
query GetCampaignGroups($first: Int!, $after: String) {
    campaignGroups(first: $first, after: $after) {
        nodes {
            id
            name
            state
            budget
            startDate
            endDate
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
