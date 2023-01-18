from posthog.queries import person_distinct_id_query
from clickhouse_driver.util.escape import escape_params

def test_person_distinct_id_query(db, snapshot):
    
    pdi_query, pdi_query_params = person_distinct_id_query.get_team_distinct_ids_query(2)
    escaped_params = escape_params(pdi_query_params)
    sql = pdi_query % escaped_params
    
    assert sql == snapshot
