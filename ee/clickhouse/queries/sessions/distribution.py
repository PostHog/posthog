from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.sessions.util import entity_query_conditions
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.sessions.distribution import DIST_SQL
from posthog.models import Filter, Team


class ClickhouseSessionsDist:
    def calculate_dist(self, filter: Filter, team: Team):
        from posthog.queries.sessions.sessions import DIST_LABELS

        parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter, team.pk)

        filters, params = parse_prop_clauses(filter.properties, team.pk, has_person_id_joined=False)

        entity_conditions, entity_params = entity_query_conditions(filter, team)
        if not entity_conditions:
            return []

        params = {**params, **entity_params}
        entity_query = " OR ".join(entity_conditions)

        dist_query = DIST_SQL.format(
            team_id=team.pk,
            date_from=parsed_date_from,
            date_to=parsed_date_to,
            filters=filters if filters else "",
            sessions_limit="",
            entity_filter=f"AND ({entity_query})",
        )

        params = {**params, "team_id": team.pk, **date_params}

        result = sync_execute(dist_query, params)

        res = [{"label": DIST_LABELS[index], "count": result[0][index]} for index in range(len(DIST_LABELS))]

        return res
