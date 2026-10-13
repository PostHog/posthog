from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE


def PG_EMBEDDINGS_DATA_TABLE():
    return "pg_embeddings"


def TRUNCATE_PG_EMBEDDINGS_TABLE_SQL(on_cluster=True):
    return f"TRUNCATE TABLE IF EXISTS {PG_EMBEDDINGS_DATA_TABLE()} {ON_CLUSTER_CLAUSE(on_cluster)}"


INSERT_BULK_PG_EMBEDDINGS_SQL = """
INSERT INTO {table_name} (domain, team_id, id, vector, text, properties, is_deleted) VALUES
""".format(table_name=PG_EMBEDDINGS_DATA_TABLE())
