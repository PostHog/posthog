from dataclasses import dataclass

from .queries.advertisers import ADVERTISERS_QUERY
from .queries.campaign_groups import CAMPAIGN_GROUPS_QUERY
from .queries.campaign_stats_daily import CAMPAIGN_STATS_DAILY_QUERY
from .queries.campaigns import CAMPAIGNS_QUERY
from .queries.conversion_trackers import CONVERSION_TRACKERS_QUERY
from .queries.creatives import CREATIVES_QUERY

STACKADAPT_GRAPHQL_URL = "https://api.stackadapt.com/graphql"
STACKADAPT_DEFAULT_PAGE_SIZE = 100

ADVERTISERS = "advertisers"
CAMPAIGN_GROUPS = "campaign_groups"
CAMPAIGNS = "campaigns"
CAMPAIGN_STATS_DAILY = "campaign_stats_daily"
CREATIVES = "creatives"
CONVERSION_TRACKERS = "conversion_trackers"


@dataclass
class StackAdaptGraphQLEndpoint:
    name: str
    query: str
    connection_path: str


STACKADAPT_GRAPHQL_ENDPOINTS: dict[str, StackAdaptGraphQLEndpoint] = {
    ADVERTISERS: StackAdaptGraphQLEndpoint(
        name=ADVERTISERS,
        query=ADVERTISERS_QUERY,
        connection_path="advertisers",
    ),
    CAMPAIGN_GROUPS: StackAdaptGraphQLEndpoint(
        name=CAMPAIGN_GROUPS,
        query=CAMPAIGN_GROUPS_QUERY,
        connection_path="campaignGroups",
    ),
    CAMPAIGNS: StackAdaptGraphQLEndpoint(
        name=CAMPAIGNS,
        query=CAMPAIGNS_QUERY,
        connection_path="campaigns",
    ),
    CAMPAIGN_STATS_DAILY: StackAdaptGraphQLEndpoint(
        name=CAMPAIGN_STATS_DAILY,
        query=CAMPAIGN_STATS_DAILY_QUERY,
        connection_path="campaignPerformance",
    ),
    CREATIVES: StackAdaptGraphQLEndpoint(
        name=CREATIVES,
        query=CREATIVES_QUERY,
        connection_path="creatives",
    ),
    CONVERSION_TRACKERS: StackAdaptGraphQLEndpoint(
        name=CONVERSION_TRACKERS,
        query=CONVERSION_TRACKERS_QUERY,
        connection_path="conversionTrackers",
    ),
}
