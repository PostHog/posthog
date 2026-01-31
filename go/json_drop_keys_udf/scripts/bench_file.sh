#!/usr/bin/env bash
set -euo pipefail

BENCH_URL="https://clickhouse-public-datasets.s3.amazonaws.com/bluesky/file_0001.json.gz"
BENCH_DIR="bench"
DEFAULT_FILE="$BENCH_DIR/benchmark.ndjson"
DEFAULT_GZ="$DEFAULT_FILE.gz"

file="${1:-$DEFAULT_FILE}"
app="${2:-bin/json_drop_keys_udf}"

# Download benchmark data if using default file and it doesn't exist
if [[ "$file" == "$DEFAULT_FILE" && ! -f "$file" ]]; then
  if [[ ! -f "$DEFAULT_GZ" ]]; then
    echo "Downloading benchmark data..." >&2
    mkdir -p "$BENCH_DIR"
    curl -fSL --progress-bar -o "$DEFAULT_GZ" "$BENCH_URL"
    echo "Downloaded to $DEFAULT_GZ" >&2
  fi
  echo "Decompressing benchmark data..." >&2
  gzip -dc "$DEFAULT_GZ" > "$DEFAULT_FILE"
fi

# If a gzip file is provided, decompress it before running the benchmark.
if [[ "$file" == *.gz ]]; then
  decompressed="${file%.gz}"
  if [[ ! -f "$decompressed" ]]; then
    echo "Decompressing $file..." >&2
    gzip -dc "$file" > "$decompressed"
  fi
  file="$decompressed"
fi

if [[ ! -f "$file" ]]; then
  echo "Input file not found: $file" >&2
  exit 1
fi

if [[ ! -x "$app" ]]; then
  echo "Building $app..." >&2
  go build -o "$app" ./cmd/json_drop_keys_udf
fi

case "$file" in
  *.gz)
    bytes=$(gzip -dc "$file" | wc -c | tr -d ' ')
    cat_cmd=(gzip -dc "$file")
    ;;
  *.lz4)
    bytes=$(lz4 -dc "$file" | wc -c | tr -d ' ')
    cat_cmd=(lz4 -dc "$file")
    ;;
  *)
    bytes=$(wc -c < "$file" | tr -d ' ')
    cat_cmd=(cat "$file")
    ;;
esac

python3 - "$file" "$app" "$bytes" "${cat_cmd[@]}" <<'PY'
import shlex
import subprocess
import sys
import time

file = sys.argv[1]
app = sys.argv[2]
byte_count = int(sys.argv[3])
cat_cmd = sys.argv[4:]

cmd = " ".join(shlex.quote(arg) for arg in cat_cmd)
cmd = f"{cmd} | {shlex.quote(app)} \"['identity']\" > /dev/null"
runs = 5
elapsed_times = []

for i in range(runs):
    start = time.perf_counter()
    subprocess.run(cmd, shell=True, check=True)
    elapsed = time.perf_counter() - start
    elapsed_times.append(elapsed)
    print(f"Run {i + 1}: {elapsed:.6f} seconds")

avg_elapsed = sum(elapsed_times) / runs
mb = byte_count / (1024 * 1024)
mb_s = mb / avg_elapsed if avg_elapsed > 0 else 0.0
print(f"Input bytes: {byte_count}")
print(f"Average seconds: {avg_elapsed:.6f}")
print(f"Average throughput: {mb_s:.2f} MiB/s")
PY
