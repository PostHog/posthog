#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

arch=$(uname -m)
case "$arch" in
  x86_64|amd64)
    arch=amd64
    ;;
  arm64|aarch64)
    arch=arm64
    ;;
  *)
    echo "Unsupported architecture: $arch" >&2
    exit 1
    ;;
 esac

UDF_BIN="$ROOT_DIR/bin/json_drop_keys_udf-linux-$arch"
"$ROOT_DIR/scripts/build.sh"

export UDF_BIN
export COMPOSE_PROJECT_NAME=json_drop_keys_udf

USER_FILES_DIR=$(mktemp -d)
cp "$ROOT_DIR/testdata/input.tsv" "$USER_FILES_DIR/input.tsv"
cp "$ROOT_DIR/testdata/bad_input.tsv" "$USER_FILES_DIR/bad_input.tsv"
export USER_DATA="$USER_FILES_DIR"

cleanup() {
  if docker compose -f "$COMPOSE_FILE" ps -q clickhouse >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" exec -T clickhouse \
      sh -c "chown -R $(id -u):$(id -g) /var/lib/clickhouse/user_files" >/dev/null 2>&1 || true
  fi
  rm -rf "$USER_FILES_DIR" >/dev/null 2>&1 || true
  docker compose -f "$COMPOSE_FILE" down -v --remove-orphans
}
trap cleanup EXIT

docker compose -f "$COMPOSE_FILE" up -d --wait

retries=15
until docker compose -f "$COMPOSE_FILE" exec -T clickhouse clickhouse-client --query "SELECT 1" >/dev/null 2>&1; do
  retries=$((retries - 1))
  if [[ $retries -le 0 ]]; then
    echo "ClickHouse did not become ready" >&2
    exit 1
  fi
  sleep 1
 done

OUTPUT_FILE=$(mktemp)

docker compose -f "$COMPOSE_FILE" exec -T clickhouse clickhouse-client \
  --query "SELECT JSONDropKeys(['a'])(x) FROM file('input.tsv', 'TabSeparated', 'x String') FORMAT TabSeparated" \
  > "$OUTPUT_FILE"

diff -u "$ROOT_DIR/testdata/expected.tsv" "$OUTPUT_FILE"
rm -f "$OUTPUT_FILE"

set +e
BAD_LOG=$(mktemp)
docker compose -f "$COMPOSE_FILE" exec -T clickhouse clickhouse-client \
  --query "SELECT JSONDropKeys(['a'])(x) FROM file('bad_input.tsv', 'TabSeparated', 'x String') FORMAT TabSeparated" \
  >/dev/null 2> "$BAD_LOG"

status=$?
set -e

if [[ $status -eq 0 ]]; then
  echo "Expected UDF failure on malformed JSON but query succeeded." >&2
  rm -f "$BAD_LOG"
  exit 1
fi

rm -f "$BAD_LOG"

echo "Integration test passed."
