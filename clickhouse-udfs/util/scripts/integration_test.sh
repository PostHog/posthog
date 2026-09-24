#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
# The repo's .envrc exports COMPOSE_PROJECT_NAME=posthog. Under that name this ClickHouse replaces the dev stack's
# clickhouse container, and the cleanup's `down --remove-orphans` removes every other dev stack container.
export COMPOSE_PROJECT_NAME=clickhouse-udfs-util-test
TEMP_DIR=$(mktemp -d)
UDFS=(
    decompress
    json_drop_keys
    json_clean_posthog_event_properties
    json_clean_posthog_person_properties
    json_clean_posthog_temporary_properties
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
        decompress)
            echo "SELECT hex(decompress(unhex(data), codec)) FROM file('$1/stateless/$2', 'TabSeparated', 'codec String, data String') SETTINGS max_block_size = 2, max_threads = 1 FORMAT TabSeparated"
            ;;
        json_drop_keys)
            echo "SELECT JSONDropKeys(['a'])(x) FROM $input FORMAT TabSeparated"
            ;;
        json_clean_posthog_event_properties)
            echo "SELECT JSONCleanPostHogEventProperties(x) FROM $input FORMAT TabSeparated"
            ;;
        json_clean_posthog_person_properties)
            echo "SELECT JSONCleanPostHogPersonProperties(x) FROM $input FORMAT TabSeparated"
            ;;
        json_clean_posthog_temporary_properties)
            echo "SELECT JSONCleanPostHogTemporaryProperties(x) FROM $input FORMAT TabSeparated"
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

query=$(cat <<'SQL'
WITH
    number % 2 = 0 AS compressed,
    if(compressed, unhex('170000006068656c6c6f200600d06f2068656c6c6f2068656c6c6f'), 'plain') AS data
SELECT countIf(
    if(compressed, decompress(data, 'LZ4SizePrefixed'), data)
        != if(compressed, 'hello hello hello hello', 'plain')
)
FROM numbers(10000)
SETTINGS short_circuit_function_evaluation = 'force_enable', max_block_size = 128, max_threads = 2
SQL
)
output=$(docker compose -f "$COMPOSE_FILE" exec -T clickhouse clickhouse-client --query "$query")
if [[ "$output" != "0" ]]; then
    echo "Expected mixed compressed/plain rows to round-trip across pool chunks, got: $output" >&2
    exit 1
fi
echo "Passed mixed compressed/plain pool chunks."

query=$(cat <<'SQL'
WITH concat('{"x":', repeat('[', 24), '[0]', repeat(',null]', 24), '}') AS raw
SELECT
    JSONExtractString(toJSONString(CAST(JSONCleanPostHogEventProperties(raw) AS JSON(max_dynamic_paths=0))), '$unparseable_properties') = raw,
    JSONExtractString(toJSONString(CAST(JSONCleanPostHogPersonProperties(raw) AS JSON(max_dynamic_paths=0))), '$unparseable_properties') = raw,
    toJSONString(CAST(JSONCleanPostHogTemporaryProperties(raw) AS JSON(max_dynamic_paths=0))) = '{}'
SETTINGS max_threads = 1, max_memory_usage = 268435456
FORMAT TabSeparated
SQL
)
output=$(docker compose -f "$COMPOSE_FILE" exec -T clickhouse clickhouse-client --query "$query")
if [[ "$output" != $'1\t1\t1' ]]; then
    echo "Expected array quarantine to preserve the input and produce castable JSON, got: $output" >&2
    exit 1
fi
echo "Passed nested-array quarantine JSON casts."

# ClickHouse started each pooled UDF process above while a client connection was open. A UDF process that keeps a
# copy of a client socket holds the connection open after the server closes it, so the client's next request on
# that connection never gets a response. Run as the clickhouse user, which owns the UDF processes.
docker compose -f "$COMPOSE_FILE" exec -T -u clickhouse clickhouse bash -s <<'BASH'
set -euo pipefail
checked=0
leaks=0
for proc in /proc/[0-9]*; do
    args=()
    mapfile -d '' args 2>/dev/null < "$proc/cmdline" || continue
    # A wrapper runs as `<shell> /var/lib/clickhouse/user_scripts/<script>`, and it starts its binary from /tmp.
    if [[ "${args[1]:-}" != /var/lib/clickhouse/user_scripts/* && "${args[0]:-}" != /tmp/* ]]; then
        continue
    fi
    checked=$((checked + 1))
    inspected=0
    for fd in "$proc"/fd/*; do
        target=$(readlink "$fd" 2>/dev/null) || continue
        inspected=$((inspected + 1))
        if [[ "$target" == socket:* ]]; then
            echo "UDF process '${args[*]}' holds descriptor ${fd##*/} ($target)." >&2
            leaks=$((leaks + 1))
        fi
    done
    # A UDF process always has stdin open, so a live process with no readable descriptor means this check cannot
    # see its descriptors, for example because it runs as another user. That must fail, not pass as clean.
    if ((inspected == 0)) && [[ -e "$proc" ]]; then
        echo "Cannot read the descriptors of UDF process '${args[*]}'." >&2
        exit 1
    fi
done
if ((checked == 0)); then
    echo "Expected running pooled UDF processes, found none." >&2
    exit 1
fi
if ((leaks > 0)); then
    exit 1
fi
BASH
echo "Passed pooled UDF processes hold no sockets."
