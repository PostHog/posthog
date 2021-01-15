from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.sessions.distribution import DIST_SQL
from posthog.models import Filter, Team


class ClickhouseSessionsDist:
    def calculate_dist(self, filter: Filter, team: Team):
        from posthog.queries.sessions.sessions import DIST_LABELS

        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter, team.pk)

        filters, params = parse_prop_clauses(filter.properties, team.pk)
        dist_query = DIST_SQL.format(
            team_id=team.pk,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
            filters=filters if filter.properties else "",
            sessions_limit="",
        )

        params = {**params, "team_id": team.pk}

        result = sync_execute(dist_query, params)

        res = [{"label": DIST_LABELS[index], "count": result[0][index]} for index in range(len(DIST_LABELS))]

        return res
