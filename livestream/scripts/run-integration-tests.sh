#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

COMPOSE_FILE="docker-compose.integration.yml"
POLL_INTERVAL=1
POLL_TIMEOUT=30

cleanup() {
    echo "--- Tearing down Redis cluster ---"
    docker compose -f "$COMPOSE_FILE" down -v
}
trap cleanup EXIT

echo "--- Starting Redis cluster ---"
docker compose -f "$COMPOSE_FILE" up -d

echo "--- Waiting for cluster to be ready (timeout: ${POLL_TIMEOUT}s) ---"
elapsed=0
while true; do
    if [ "$elapsed" -ge "$POLL_TIMEOUT" ]; then
        echo "ERROR: Cluster not ready after ${POLL_TIMEOUT}s"
        exit 1
    fi

    cluster_info=$(docker compose -f "$COMPOSE_FILE" exec -T redis-node-1 redis-cli -p 7001 cluster info 2>/dev/null || true)
    state=$(echo "$cluster_info" | grep -o 'cluster_state:ok' || true)
    known=$(echo "$cluster_info" | sed -n 's/^cluster_known_nodes:\([0-9]*\).*/\1/p')

    if [ "$state" = "cluster_state:ok" ] && [ "$known" = "3" ]; then
        echo "Cluster ready (state=ok, nodes=3)"
        break
    fi

    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
done

echo "--- Running integration tests ---"
test_exit=0
go test ./events/ -tags=integration -v -timeout 30s "$@" || test_exit=$?

exit "$test_exit"
