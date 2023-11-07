# flake8: noqa
from typing import Dict, List, Tuple

import structlog
from clickhouse_driver.errors import Error as ClickhouseError
from django.conf import settings
from statshog.defaults.django import statsd

from posthog.client import sync_execute

logger = structlog.get_logger(__name__)


def get_clickhouse_schema() -> List[Tuple[str, str, str]]:
    """
    Get the ClickHouse schema of all tables that
    are not materialized views (aka: .inner_id.%)
    """
    return sync_execute(
        """
        SELECT
            name as table_name,
            create_table_query,
            hostname() as hostname
        FROM
            clusterAllReplicas('{cluster}', system, tables)
        WHERE
            database == '{database}'
        AND
            table_name NOT LIKE '.inner_id.%'
        """.format(cluster=settings.CLICKHOUSE_CLUSTER, database=settings.CLICKHOUSE_DATABASE)
    )


def get_clickhouse_nodes() -> List[Tuple[str]]:
    """
    Get the ClickHouse nodes part of the cluster
    """
    return sync_execute(
        """
        SELECT
            host_name
        FROM
            system.clusters
        WHERE
            cluster == '{cluster}'

        """.format(cluster=settings.CLICKHOUSE_CLUSTER)
    )


def get_clickhouse_schema_drift(
    clickhouse_nodes: List[Tuple[str]], clickhouse_schema: List[Tuple[str, str, str]]
) -> List:
    diff = []  # type: List[str]
    if len(clickhouse_nodes) <= 1:
        # There can't be drift if we have less than 2 nodes
        return diff

    # Parse query rows and put them in a Dict like:
    # {
    #   "table1": {"schema1": ["host1", "host2", "host3"]},
    #   "table2": {
    #     "schema2": ["host1"],
    #     "schema2-different": ["host2"],
    #     "schema2-different-bis": ["host3"]},
    # }
    tables = {}  # type: Dict
    for table_name, schema, node_name in clickhouse_schema:
        if table_name not in tables:
            tables[table_name] = {}
        if schema not in tables[table_name]:
            tables[table_name][schema] = []
        tables[table_name][schema].append(node_name)

    # For each table
    for table_name, table_schemas in tables.items():
        # Check if we have multiple schemas
        if len(table_schemas) > 1:
            diff.append(table_name)
        # Check if the sum of all the hosts across a schema is
        # equal to the number of hosts in the cluster
        schema_count = sum(len(v) for v in table_schemas.values())
        if schema_count != len(clickhouse_nodes):
            diff.append(table_name)
    return diff


def check_clickhouse_schema_drift(
    clickhouse_nodes: List[Tuple[str]] = [],
    clickhouse_schema: List[Tuple[str, str, str]] = [],
) -> None:
    try:
        if not clickhouse_nodes:
            clickhouse_nodes = get_clickhouse_nodes()
        if not clickhouse_schema:
            clickhouse_schema = get_clickhouse_schema()
    except ClickhouseError:
        logger.error("check_clickhouse_schema_drift_error", exc_info=True)
        return  # no need to raise as we execute this often

    drift = get_clickhouse_schema_drift(clickhouse_nodes, clickhouse_schema)

    logger.info("check_clickhouse_schema_drift", table_count=len(drift), tables=drift)

    # Send to statsd the total count of drifting tables as well as a metric for each table
    for table_name in drift:
        statsd.gauge("clickhouse_schema_drift_table.{}".format(table_name), 1)
    statsd.gauge("clickhouse_schema_drift_table_count", len(drift))
