#!/usr/bin/env bash
# Longer watch: emit when the seed box resolves (running/failed/gone) or the
# build output advances, else report still-stuck after ~30m.
H="https://hogland-dev.hedgehog-kitefin.ts.net"
B=box-4e33f817f801
OUT=/private/tmp/claude-501/-Users-julian-workspace-hogland/495dbf65-31fa-43c4-acac-2928630570cb/tasks/b4182u5tw.output
base=$(wc -l < "$OUT" 2>/dev/null || echo 1)
for i in $(seq 1 90); do
  s=$(/tmp/hogland --host "$H" box get "$B" 2>/dev/null | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('status','ERR') if 'id' in d else 'GONE')
except Exception:
    print('ERR')")
  case "$s" in
    running) echo "RUNNING: seed booted after ~$((i*20))s — setup script executing now"; exit 0;;
    failed)  echo "FAILED: seed status=failed after ~$((i*20))s"; exit 0;;
    GONE)    echo "GONE: seed reaped after ~$((i*20))s (metal placement gave up)"; exit 0;;
  esac
  cur=$(wc -l < "$OUT" 2>/dev/null || echo 1)
  if [ "$cur" -gt "$base" ]; then echo "BUILD ADVANCED: $(tail -1 "$OUT")"; exit 0; fi
  sleep 20
done
echo "STILL_PLACING: seed stuck in placing ~30m more (node hogd not acknowledging it)"
