def check_clickhouse_query_status(query_id):
    from ee.clickhouse.client import sync_execute

    query = f"SELECT max(CAST(type, 'Int8')) FROM system.query_log WHERE query LIKE '%%{query_id}%%'"
    query_status = sync_execute(query)[0][0]
    return query_status
