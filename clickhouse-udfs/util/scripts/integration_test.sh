#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
TEMP_DIR=$(mktemp -d)
UDFS=(
    json_drop_keys
    json_clean_posthog_event_properties
    json_clean_posthog_person_properties
    json_strip_empty_strings_and_nulls
)

cleanup() {
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

query_for() {
    local input="file('$1/stateless/$2', 'TabSeparated', 'x String')"
    case "$1" in
        json_drop_keys)
            echo "SELECT JSONDropKeys(['a'])(x) FROM $input FORMAT TabSeparated"
            ;;
        json_clean_posthog_event_properties)
            echo "SELECT JSONCleanPostHogEventProperties(x) FROM $input FORMAT TabSeparated"
            ;;
        json_clean_posthog_person_properties)
            echo "SELECT JSONCleanPostHogPersonProperties(x) FROM $input FORMAT TabSeparated"
            ;;
        json_strip_empty_strings_and_nulls)
            echo "SELECT JSONStripEmptyStringsAndNulls(x) FROM $input FORMAT TabSeparated"
            ;;
    esac
}

docker compose -f "$COMPOSE_FILE" up -d --wait
docker compose -f "$COMPOSE_FILE" cp "$ROOT_DIR/testdata/." clickhouse:/var/lib/clickhouse/user_files/

for udf in "${UDFS[@]}"; do
    stateless_dir="$ROOT_DIR/testdata/$udf/stateless"

    for test_file in "$stateless_dir"/*.tsv; do
        test_name=$(basename "$test_file")
        reference="${test_file%.tsv}.reference"
        output_file="$TEMP_DIR/$udf-$test_name.output"
        query=$(query_for "$udf" "$test_name")

        if [[ "$test_name" == *.fail.tsv ]]; then
            if docker compose -f "$COMPOSE_FILE" exec -T clickhouse clickhouse-client --query "$query" \
                >/dev/null 2> "$output_file"; then
                echo "Expected $udf $test_name to fail, but the query succeeded." >&2
                exit 1
            fi
            expected_error=$(<"$reference")
            if [[ -n "$expected_error" ]] && ! grep -Fq "$expected_error" "$output_file"; then
                echo "Expected $udf $test_name error to contain: $expected_error" >&2
                cat "$output_file" >&2
                exit 1
            fi
        else
            docker compose -f "$COMPOSE_FILE" exec -T clickhouse clickhouse-client --query "$query" > "$output_file"
            diff -u "$reference" "$output_file"
        fi

        echo "Passed $udf/$test_name."
    done
done
