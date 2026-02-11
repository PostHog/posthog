CAMPAIGN_STATS_DAILY_QUERY = """
query GetCampaignStatsByDay(
    $first: Int!
    $after: String
    $startTime: DateTime!
    $endTime: DateTime!
) {
    campaignPerformance(
        first: $first
        after: $after
        filter: {
            startTime: $startTime
            endTime: $endTime
            granularity: DAY
        }
    ) {
        nodes {
            campaign {
                id
                name
            }
            granularity {
                startTime
            }
            metrics {
                impressions
                uniqueImpressions
                clicks
                cost
                conversions
                conversionRevenue
                clickConversions
                impressionConversions
                videoStarts
                videoCompletions
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}
"""
