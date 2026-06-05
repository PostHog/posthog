#!/bin/sh
# Run a semgrep scan with a wall-clock watchdog and a single retry.
#
# Why this exists: semgrep-core can spin in target discovery (the Semgrepignore
# v2 path walk) far past --timeout, which only bounds per-rule *matching*. A
# wedged worker pins one CPU with no further output until the job hits its
# timeout-minutes — a recurring, nondeterministic CI false-failure that has hit
# every semgrep job (and master). The per-rule --timeout does not cover this
# phase, so we bound it externally here.
#
# On a wedge this logs the stuck worker's open source paths (to pin the
# offending file for an upstream report), kills it, and retries once — the hang
# is nondeterministic, so a retry almost always succeeds. Real findings (exit 1)
# and other errors propagate unchanged. Cap is overridable via SEMGREP_CAP_SECONDS.

CAP="${SEMGREP_CAP_SECONDS:-900}"
attempt=1

while :; do
    semgrep "$@" &
    sp=$!

    # Watchdog: snapshot + kill the run if it exceeds CAP seconds.
    (
        e=0
        while kill -0 "$sp" 2>/dev/null; do
            sleep 15
            e=$((e + 15))
            [ "$e" -lt "$CAP" ] && continue
            echo "::warning::semgrep exceeded ${CAP}s (attempt ${attempt}) — capturing the stuck worker, then killing"
            core=$(ps -o pid,stat,args | awk '/[s]emgrep-core/ && $2 ~ /R/ { print $1; exit }')
            if [ -n "$core" ]; then
                echo "stuck semgrep-core pid=${core} — open source paths (likely the trigger):"
                for fd in /proc/"$core"/fd/*; do readlink "$fd"; done 2>/dev/null \
                    | grep -Ev 'pipe:|socket:|/dev/|anon_' || true
            fi
            kill -9 "$sp" 2>/dev/null || true
            for p in $(ps -o pid,args | awk '/[s]emgrep-core/ { print $1 }'); do
                kill -9 "$p" 2>/dev/null || true
            done
            break
        done
    ) &
    wd=$!

    wait "$sp" && rc=0 || rc=$?
    kill "$wd" 2>/dev/null || true

    # 137 = SIGKILL from our watchdog (a wedge). Retry once; everything else
    # (0 success, 1 findings, 2 error) propagates so real failures still block.
    if [ "$rc" -eq 137 ] && [ "$attempt" -lt 2 ]; then
        attempt=2
        echo "::warning::retrying semgrep once after wedge"
        continue
    fi
    exit "$rc"
done
