# ClickHouse multi-node dev stack targets
# See: docker-compose.dev-coordinator.yml

.PHONY: ch-stack-up ch-stack-down ch-test-multinode

ch-stack-up:
	docker compose -f docker-compose.dev.yml -f docker-compose.dev-coordinator.yml \
		up -d clickhouse clickhouse-coordinator clickhouse-logs keeper keeper-logs kafka

ch-stack-down:
	docker compose -f docker-compose.dev.yml -f docker-compose.dev-coordinator.yml down -v

ch-test-multinode:
	@docker ps --format '{{.Names}}' | grep -q posthog-clickhouse-1 || \
	  { echo "ERROR: Start dev stack first: make ch-stack-up"; exit 1; }
	@docker ps --format '{{.Names}}' | grep -q posthog-clickhouse-coordinator-1 || \
	  { echo "ERROR: clickhouse-coordinator not running. Run: make ch-stack-up"; exit 1; }
	@docker ps --format '{{.Names}}' | grep -q posthog-clickhouse-logs-1 || \
	  { echo "ERROR: clickhouse-logs not running. Run: make ch-stack-up"; exit 1; }
	SECRET_KEY=test-key-not-real DATABASE_URL=postgres://localhost/posthog DEBUG=1 \
	  .venv/bin/pytest posthog/clickhouse/test/test_e2e_multinode.py -v -m multinode
