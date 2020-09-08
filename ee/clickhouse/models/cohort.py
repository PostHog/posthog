from ee.clickhouse.client import ch_client
from ee.clickhouse.models.action import format_action_table_name
from ee.clickhouse.sql.clickhouse import DROP_TABLE_IF_EXISTS_SQL
from ee.clickhouse.sql.cohort import (
    CALCULATE_COHORT_PEOPLE_SQL,
    FILTER_EVENT_DISTINCT_ID_BY_ACTION_SQL,
    INSERT_INTO_COHORT_TABLE,
    PERSON_PROPERTY_FILTER_SQL,
    create_cohort_mapping_table_sql,
)
from posthog.models import Action, Cohort, Filter


def format_cohort_table_name(cohort: Cohort) -> str:
    return "cohort_" + str(cohort.team.pk) + "_" + str(cohort.pk)


def populate_cohort_person_table(cohort: Cohort) -> None:
    cohort_table_name = format_cohort_table_name(cohort)

    ch_client.execute(DROP_TABLE_IF_EXISTS_SQL.format(cohort_table_name))

    ch_client.execute(create_cohort_mapping_table_sql(table_name=cohort_table_name))

    person_id_query = format_filter_query(cohort)

    final_query = INSERT_INTO_COHORT_TABLE.format(table_name=cohort_table_name, query=person_id_query)
    ch_client.execute(final_query)


def format_filter_query(cohort: Cohort) -> str:
    filters = []
    for group in cohort.groups:
        if group.get("action_id"):
            action = Action.objects.get(pk=group["action_id"], team_id=cohort.team.pk)
            table_name = format_action_table_name(action)
            filters.append("(" + FILTER_EVENT_DISTINCT_ID_BY_ACTION_SQL.format(table_name=table_name) + ")")
        elif group.get("properties"):
            filter = Filter(data=group)
            prop_filter = filter.format_ch(team_id=cohort.team.pk)
            filters.append("(" + PERSON_PROPERTY_FILTER_SQL.format(filters=prop_filter) + ")")

    separator = " OR person_id IN "
    joined_filter = separator.join(filters)
    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(query=joined_filter)
    return person_id_query
