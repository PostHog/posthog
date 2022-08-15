#!/bin/bash
set -e

USER="default"

while test $# -gt 0; do
  case "$1" in
    -h|--help)
      echo "This is a script to measure performance of a clickhouse query against a live database instance."
      echo ""
      echo "USAGE:"
      echo "    measure.sh [FLAGS]"
      echo ""
      echo "EXAMPLE:"
      echo "    measure.sh --clickhouse-server clickhouse-server --tunnel-server some-server --password PW --query-file some-query.sql"
      echo ""
      echo "FLAGS:"
      echo "    -h, --help                  Print this help information."
      echo "    -q, --query-file            Send query to measure to here"
      echo "    -s, --clickhouse-server     Address of clickhouse server"
      echo "    -t, --tunnel-server         Address of server to tunnel clickhouse from"
      echo "    -u, --user                  Clickhouse user (default: default)"
      echo "    -p, --password              Clickhouse user password"
      echo "    --explain                   Output explain for query"
      echo "    --drop-cache                Drop clickhouse cache before executing the query. Don't use against production"
      exit 0
      ;;
    -q|--query-file)
      QUERY_FILE="$2"
      shift
      shift
      ;;
    -s|--clickhouse-server)
      CLICKHOUSE_SERVER="$2"
      shift
      shift
      ;;
    -t|--tunnel-server)
      TUNNEL_SERVER="$2"
      shift
      shift
      ;;
    -u|--user)
      USER="$2"
      shift
      shift
      ;;
    -p|--password)
      PASSWORD="$2"
      shift
      shift
      ;;
    --explain)
      EXPLAIN=1
      shift
      ;;
    --drop-cache)
      DROP_CACHE=1
      shift
      ;;
    --no-flamegraphs)
      NO_FLAMEGRAPHS=1
      shift
      ;;
    *)
      break
      ;;
  esac
done

trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT

QUERY_HOST="$CLICKHOUSE_SERVER"
PORT="8123"

QUERY=$(cat $QUERY_FILE)
RANDOM_QUERY_ID="$RANDOM"
QUERY_WITH_SETTINGS="
-- measure.sh:$RANDOM_QUERY_ID
${QUERY}
SETTINGS allow_introspection_functions=1,
         query_profiler_real_time_period_ns=40000000,
         query_profiler_cpu_time_period_ns=40000000,
         memory_profiler_step=1048576,
         max_untracked_memory=1048576,
         memory_profiler_sample_probability=0.01,
         use_uncompressed_cache=0,
         max_execution_time=400
"
# echo "$QUERY"

if [[ -v TUNNEL_SERVER ]]; then
  echo "Setting up SSH tunnel..."

  PORT="8124"
  QUERY_HOST="localhost"

  ssh -L "$PORT:$CLICKHOUSE_SERVER:8123" -N "$TUNNEL_SERVER" &
  sleep 5
fi

CLICKHOUSE_QUERY_ENDPOINT="http://${USER}:${PASSWORD}@${QUERY_HOST}:$PORT/?database=posthog"
CLICKHOUSE_DSN_STRING="http://${USER}:${PASSWORD}@${QUERY_HOST}:$PORT"


if [[ -v EXPLAIN ]]; then
    echo "Query plan:"
    # echo "EXPLAIN header=1, json=1, actions=1 ${QUERY} FORMAT TSVRaw" | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @- | jq .
    # echo "EXPLAIN PIPELINE header=1 ${QUERY} FORMAT TSVRaw" | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @-
    echo "EXPLAIN PIPELINE graph=1, header=1 ${QUERY}" | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @-
else
  if [[ -v DROP_CACHE ]]; then
      echo "Dropping mark cache..."
      echo "SYSTEM DROP MARK CACHE" | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @- &> /dev/null
  fi

  echo "Executing query..."
  echo "$QUERY_WITH_SETTINGS" | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @- # &> /dev/null

  echo "Flushing logs..."
  echo "SYSTEM FLUSH LOGS" | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @- &> /dev/null

  echo "Getting query ID..."
  QUERY_ID=$(echo "
      SELECT query_id
      FROM system.query_log
      WHERE
          query NOT LIKE '%query_log%'
          AND query LIKE '%measure.sh:$RANDOM_QUERY_ID%'
          AND type = 'QueryFinish'
      ORDER BY query_start_time desc
      LIMIT 1
  " | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @-)

  echo "Query id: $QUERY_ID"

  echo "Query stats:"
  echo "
      SELECT
          event_time,
          query_duration_ms,
          read_rows,
          formatReadableSize(read_bytes) as read_size,
          result_rows,
          formatReadableSize(result_bytes) as result_size,
          formatReadableSize(memory_usage) as memory_usage,
          tables,
          columns
      FROM system.query_log
      WHERE query_id='$QUERY_ID' AND type = 'QueryFinish'
      LIMIT 1
      FORMAT Vertical
  " | curl "$CLICKHOUSE_QUERY_ENDPOINT" -s --data-binary @- | sed 's/^/    /' | tail -n +2

  FILENAME=$(basename -- "$QUERY_FILE")
  OUTPUT_PATH="$(date +%s)-${QUERY_ID}-${FILENAME%.*}"


  if [[ -z "$NO_FLAMEGRAPHS" ]]; then
    clickhouse-flamegraph --query-id "$QUERY_ID" --clickhouse-dsn "$CLICKHOUSE_DSN_STRING" --console --date-from "2021-01-01" -o "${OUTPUT_PATH}" --width 1900

    chromium-browser ${OUTPUT_PATH}/*
  fi
fi
