"""
Migration to create agent_logs tables for Twig agent log ingestion.

This creates a dedicated Kafka→ClickHouse pipeline for Twig agent logs,
bypassing the LogsIngestionConsumer for lower latency and independence
from customer log quotas.

Architecture:
    Twig Agent → OTEL → capture-logs-agent → Kafka (agent_logs)
                                                   ↓
                                    kafka_agent_logs (Kafka engine)
                                                   ↓
                                    kafka_agent_logs_mv → agent_logs (dedicated table)

Tables created (on dedicated agent_logs nodes):
- agent_logs: Dedicated MergeTree table optimized for task/run queries
- kafka_agent_logs: Kafka engine table consuming from agent_logs topic
- kafka_agent_logs_mv: Materialized view transforming to agent_logs table
- kafka_agent_logs_kafka_metrics_mv: Materialized view for consumer lag metrics
"""

from posthog.clickhouse.agent_logs import (
    AGENT_LOGS_TABLE_SQL,
    KAFKA_AGENT_LOGS_METRICS_MV_SQL,
    KAFKA_AGENT_LOGS_MV_SQL,
    KAFKA_AGENT_LOGS_TABLE_SQL,
    LOGS_KAFKA_METRICS_TABLE_SQL,
)
from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions

# All agent_logs tables live on dedicated agent_logs nodes, isolated from
# customer log nodes. In dev/test environments (non-cloud), migrations run
# on ALL nodes since we don't have separate ClickHouse topologies.
operations = [
    # 1. Create the dedicated agent_logs table
    run_sql_with_exceptions(AGENT_LOGS_TABLE_SQL(), node_roles=[NodeRole.AGENT_LOGS]),
    # 2. Create the Kafka engine table
    run_sql_with_exceptions(KAFKA_AGENT_LOGS_TABLE_SQL(), node_roles=[NodeRole.AGENT_LOGS]),
    # 3. Create the MV that writes to agent_logs table
    run_sql_with_exceptions(KAFKA_AGENT_LOGS_MV_SQL(), node_roles=[NodeRole.AGENT_LOGS]),
    # 4. Ensure logs_kafka_metrics table exists (already present on logs cluster in prod, needed in CI/dev)
    run_sql_with_exceptions(LOGS_KAFKA_METRICS_TABLE_SQL(), node_roles=[NodeRole.AGENT_LOGS]),
    # 5. Create metrics MV for Kafka consumer lag monitoring
    run_sql_with_exceptions(KAFKA_AGENT_LOGS_METRICS_MV_SQL(), node_roles=[NodeRole.AGENT_LOGS]),
]
