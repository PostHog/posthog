#!/usr/bin/env bash
# Watch the snapshot-build seed box until placement resolves (one notification).
H="https://hogland-dev.hedgehog-kitefin.ts.net"
seen=0
for i in $(seq 1 45); do
  json=$(/tmp/hogland --host "$H" box list 2>/dev/null)
  s=$(printf '%s' "$json" | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(d[0]['status'] if isinstance(d,list) and d else 'NONE')
except Exception:
    print('ERR')")
  [ "$s" = placing ] && seen=1
  case "$s" in
    running) echo "PLACED: running after ~$((i*20))s — setup script now executing"; exit 0;;
    failed)  echo "FAILED after ~$((i*20))s"; exit 0;;
  esac
  if [ "$seen" = 1 ] && [ "$s" = NONE ]; then
    echo "REAPED: seed box gone after ~$((i*20))s — metal placement failed again"; exit 0
  fi
  sleep 20
done
echo "TIMEOUT: last status=$s after ~15m"
