#!/usr/bin/env bash
#
# Reproducible point-lookup benchmark: new `ai_events` table vs legacy `events`
# table, for the LLM analytics single-trace view (TraceQuery).
#
# It picks N random traces in a scope (all teams, or one team) over a +/-1 day window,
# runs the new and legacy compiled queries against production ClickHouse (via Metabase),
# and reports query_duration / rows / bytes / memory pulled from system.query_log.
#
# See README.md for methodology, prerequisites, and the manual (no-script) path.
#
# Usage:
#   hogli metabase:login --region us            # once, interactive SSO
#   SCOPE=all DATE=2026-05-18 N=30 RUNS=3 ./run_benchmark.sh
#   SCOPE=<team_id> DATE=2026-05-18 N=30 RUNS=3 ./run_benchmark.sh
#
set -uo pipefail

REGION="${REGION:-us}"
SCOPE="${SCOPE:-all}"                # 'all' (every team) or a numeric team id
DATE="${DATE:-2026-05-18}"          # a day INSIDE the dual-write overlap window
N="${N:-30}"                        # number of random traces
RUNS="${RUNS:-3}"                   # repetitions per query (captures cold vs warm)
AGG_WINDOW_MIN="${AGG_WINDOW_MIN:-180}"  # how far back to scan query_log

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL="$HERE/sql"
WORK="$(mktemp -d "/tmp/trace_bench.XXXXXX")"
PREFIX="tracebench_$(date +%s)"     # unique marker per invocation

# selection window: [DATE-1d, DATE+2d) i.e. DATE +/- 1 day, inclusive
DSEL_FROM="$(python3 -c "import datetime;y,m,d='$DATE'.split('-');print(datetime.date(int(y),int(m),int(d))-datetime.timedelta(days=1))") 00:00:00"
DSEL_TO="$(python3 -c "import datetime;y,m,d='$DATE'.split('-');print(datetime.date(int(y),int(m),int(d))+datetime.timedelta(days=2))") 00:00:00"
if [ "$SCOPE" = "all" ]; then TEAM_FILTER="1 = 1"; else TEAM_FILTER="team_id = $SCOPE"; fi

echo "region=$REGION scope=$SCOPE date=$DATE (+/-1d) traces=$N runs=$RUNS"
echo "work dir: $WORK   marker prefix: $PREFIX"

# --- discover the ClickHouse PROD ONLINE database id (override with DB_ID=...) ---
if [[ -z "${DB_ID:-}" ]]; then
    DB_ID="$(hogli metabase:databases --region "$REGION" 2>/dev/null \
        | awk -F'  +' '/ClickHouse PROD .* ONLINE/ {print $1; exit}' | tr -dc '0-9')"
fi
if [[ -z "${DB_ID:-}" ]]; then
    echo "ERROR: could not find ClickHouse ONLINE db id; set DB_ID=... (see: hogli metabase:databases --region $REGION)" >&2
    exit 1
fi
echo "clickhouse db id: $DB_ID"

q () { # run a sql file, save full json response to $2
    hogli metabase:query --region "$REGION" --database-id "$DB_ID" --format json --file "$1" --save "$2" >/dev/null 2>&1
}

# --- 1. random trace selection ---
sed -e "s/@@TEAM_FILTER@@/$TEAM_FILTER/g" -e "s/@@DFROM@@/$DSEL_FROM/g" \
    -e "s/@@DTO@@/$DSEL_TO/g" -e "s/@@N@@/$N/g" \
    "$SQL/select_random.sql.tmpl" > "$WORK/select.sql"
q "$WORK/select.sql" "$WORK/select.json"
CANDS="$WORK/candidates.tsv"
python3 -c "
import json
d=json.load(open('$WORK/select.json'))
rows=d.get('data',{}).get('rows',[])
with open('$CANDS','w') as f:
    for r in rows: f.write('\t'.join(str(x) for x in r)+'\n')
print('selected', len(rows), 'traces')
"
[ -s "$CANDS" ] || { echo 'ERROR: no traces selected (check SCOPE/DATE inside retention & dual-write)'; exit 1; }

# --- 2. materialise new + legacy query per trace (centered 30-min window) ---
JOBS=()
idx=0
while IFS=$'\t' read -r team trace first_ts; do
    tt=$(printf 't%02d' "$idx")
    { read -r DF; read -r DT; } < <(python3 -c "
from datetime import datetime,timedelta
ts=datetime.strptime('$first_ts'.split('.')[0],'%Y-%m-%d %H:%M:%S')
print((ts-timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S'))
print((ts+timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S'))")
    for V in NEW OLD; do
        tmpl="$SQL/trace_query_new.sql.tmpl"; [[ "$V" == OLD ]] && tmpl="$SQL/trace_query_legacy.sql.tmpl"
        marker="${PREFIX}_${tt}_${V}"
        sed -e "s/@@MARKER@@/$marker/g" -e "s/@@TRACE@@/$trace/g" \
            -e "s/@@DFROM@@/$DF/g" -e "s/@@DTO@@/$DT/g" -e "s/@@TEAM@@/$team/g" \
            "$tmpl" > "$WORK/$marker.sql"
        JOBS+=("$WORK/$marker.sql")
    done
    idx=$((idx+1))
done < "$CANDS"

# --- 3. execute every query RUNS times ---
total=$(( ${#JOBS[@]} * RUNS )); done_n=0; fail=0
echo "executing $total queries (${#JOBS[@]} queries x $RUNS runs)..."
for run in $(seq 1 "$RUNS"); do
    for f in "${JOBS[@]}"; do
        out=$(hogli metabase:query --region "$REGION" --database-id "$DB_ID" --format json --file "$f" 2>/dev/null)
        printf '%s' "$out" | grep -q '"status": "completed"' || fail=$((fail+1))
        done_n=$((done_n+1))
        printf '\r  %d/%d (failures: %d)' "$done_n" "$total" "$fail"
    done
done
echo
[ "$fail" -gt 0 ] && echo "WARNING: $fail/$total executions did not complete — query_log only aggregates successful runs." >&2

# --- 4. aggregate from query_log ---
sed -e "s/@@PREFIX@@/$PREFIX/g" -e "s/@@WINDOW_MIN@@/$AGG_WINDOW_MIN/g" \
    "$SQL/aggregate.sql.tmpl" > "$WORK/aggregate.sql"
q "$WORK/aggregate.sql" "$WORK/agg.json"
echo
echo "=== RESULTS (scope=$SCOPE, $DATE +/-1d) ==="
python3 -c "
import json
d=json.load(open('$WORK/agg.json'))
cols=[c['name'] for c in d['data']['cols']]
rows=d['data']['rows']
w=[max(len(str(x)) for x in [c]+[r[i] for r in rows])+2 for i,c in enumerate(cols)]
print(''.join(str(c).ljust(w[i]) for i,c in enumerate(cols)))
for r in rows:print(''.join(str(v).ljust(w[i]) for i,v in enumerate(r)))"
echo
echo "raw per-run rows are in system.query_log where query LIKE '%$PREFIX%'  (work dir kept: $WORK)"
