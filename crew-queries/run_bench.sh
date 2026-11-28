#!/bin/bash
# Run rendered benchmark queries through Metabase, one at a time, saving each result as TSV.
#   crew-queries/run_bench.sh <region> <database-id> <glob>     e.g. us <id> 'q1__overview__*__7d'
# Appends wall time and status per query to crew-queries/results/<region>/runs.log. Re-running skips
# queries that already have a result file.
set -u
region="$1"; db="$2"; pattern="$3"
root="$(cd "$(dirname "$0")" && pwd)"
out="$root/results/$region"; mkdir -p "$out"
for f in "$root"/rendered/"$region"/$pattern.sql; do
    name="$(basename "$f" .sql)"
    [ -s "$out/$name.tsv" ] && continue
    start=$(date +%s)
    if bin/hogli metabase:query --region "$region" --database-id "$db" --file "$f" --save "$out/$name.tsv" > "$out/$name.out" 2>&1; then
        status=ok
    else
        status=fail; rm -f "$out/$name.tsv"
    fi
    echo "$(date -u +%FT%TZ) $name $status $(( $(date +%s) - start ))s" | tee -a "$out/runs.log"
done
