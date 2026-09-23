from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.traces import KAFKA_TRACE_SPANS_AVRO_MV
from posthog.run_mode import RunMode, run_mode

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# 0330 moved this MV to the apm nodes on dev, because that is where the `coshared/apm_ingest`
# layer is composed there. Those nodes do not host `trace_spans`; they host
# `writable_trace_spans`, the Distributed proxy into the logs cluster. The MV was still created
# with `TO trace_spans`, which does not resolve on an apm node, so span ingestion stopped on dev.
#
# Recreate it against the Distributed proxy, which is what `roles/apm/dev` has always declared.
# Dev-only: every other environment keeps the MV on the logs nodes, where `trace_spans` is local
# and the existing MV is correct, so there is nothing to recreate and no ingestion gap to spend.
#
# This assumes `writable_trace_spans` already exists on the apm nodes, as it does on dev. No SQL
# function in the repo creates it, so a dev rebuilt from scratch would still need it created by
# hand before this runs.
operations = (
    [
        run_sql_with_exceptions(f"DROP TABLE IF EXISTS {DB}.kafka_trace_spans_avro_mv", node_roles=[NodeRole.APM]),
        run_sql_with_exceptions(KAFKA_TRACE_SPANS_AVRO_MV(to_table="writable_trace_spans"), node_roles=[NodeRole.APM]),
    ]
    if run_mode() is RunMode.CLOUD_DEV
    else []
)
