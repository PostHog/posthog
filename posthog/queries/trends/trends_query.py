from posthog.models import Team, Filter
from posthog.queries.query_node_to_filter import query_node_to_filter
from posthog.queries.trends.trends import Trends
from posthog.schema import TrendsQuery, TrendsQueryResponse


def run_trends_query(
    team: Team,
    query: TrendsQuery,
) -> TrendsQueryResponse:
    data = query_node_to_filter(query)
    filter = Filter(data=data, team=team)
    trends_query = Trends()
    result = trends_query.run(filter, team)
    return TrendsQueryResponse(result=result, timezone=team.timezone)
