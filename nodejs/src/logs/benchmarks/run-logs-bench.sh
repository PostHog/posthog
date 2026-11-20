#!/usr/bin/env bash
# Benchmarks the logs consumer three ways on the same workloads: the consumer before the framework
# rewrite, the framework consumer, and the Rust port. Needs Redis on 127.0.0.1:6379.
#
#   nodejs/src/logs/benchmarks/run-logs-bench.sh [out_dir] [passes] [warmup]
#
# The "before" consumer is read from git at BASELINE_COMMIT into a gitignored directory, because
# it registers the same Prometheus metric names as the current one and must run in its own process.
set -euo pipefail

BASELINE_COMMIT="${BASELINE_COMMIT:-1c626b06c}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
OUT="$(realpath -m "${1:-${TMPDIR:-/tmp}/logs-bench}")"
PASSES="${2:-10}"
WARMUP="${3:-2}"
# Implementations alternate within each round, and compare reports each one's median round, so a
# noisy neighbour skews one sample rather than one implementation.
ROUNDS="${ROUNDS:-3}"
mkdir -p "$OUT/workloads" "$OUT/results"

baseline="$HERE/.baseline"
mkdir -p "$baseline"
for file in logs-ingestion-consumer traces-ingestion-consumer; do
    # Imports are relative to nodejs/src/logs; the two classes import each other.
    git -C "$REPO" show "$BASELINE_COMMIT:nodejs/src/logs/$file.ts" |
        sed -e "s#from '\./logs-ingestion-consumer'#from './logs-ingestion-consumer'#" \
            -e "/from '\.\/logs-ingestion-consumer'/!s#from '\./#from '../../#" >"$baseline/$file.ts"
done

cd "$REPO/nodejs"
# The shared config module requires a database URL at import time; the benchmark never connects.
bench() {
    DATABASE_URL="${DATABASE_URL:-postgres://bench:bench@127.0.0.1:1/unused}" LOG_LEVEL=warn \
        npx tsx --tsconfig tsconfig.json src/logs/benchmarks/logs-consumer-bench.ts "$@"
}

bench generate "$OUT/workloads"
run_rust=""
if [ -z "${SKIP_RUST:-}" ]; then
    if [ -f "$REPO/rust/logs-ingestion/Cargo.toml" ]; then
        run_rust=1
        (cd "$REPO/rust" && cargo build --release -q -p logs-ingestion --bin logs-ingestion-bench)
    else
        echo "rust/logs-ingestion is not in this checkout, so only the Node consumers run." >&2
    fi
fi
results=()
for round in $(seq 1 "$ROUNDS"); do
    for workload in "$OUT"/workloads/*.json; do
        name="$(basename "$workload" .json)"
        for impl in before framework; do
            result="$OUT/results/$name.node-$impl.r$round.json"
            bench run "$impl" "$workload" "$result" "$PASSES" "$WARMUP"
            results+=("$result")
        done
        if [ -n "$run_rust" ]; then
            result="$OUT/results/$name.rust.r$round.json"
            "$REPO/rust/target/release/logs-ingestion-bench" "$workload" "$PASSES" "$WARMUP" >"$result"
            results+=("$result")
        fi
    done
done
bench compare "${results[@]}" | tee "$OUT/results.md"
