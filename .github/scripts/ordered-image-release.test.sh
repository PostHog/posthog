#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "$0")/../.." && pwd)"
helper="$repository_root/.github/scripts/ordered-image-release.sh"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
system_path="$PATH"
mkdir "$scratch/shims"
cat > "$scratch/shims/timeout" <<'SHIM'
#!/usr/bin/env bash
if [ "$1" = --foreground ]; then
    printf '%s\n' "$1" >> "$TIMEOUT_ARGUMENTS"
    shift
fi
printf '%s\n' "$1" "$2" >> "$TIMEOUT_ARGUMENTS"
shift 2
exec "$@"
SHIM
cat > "$scratch/shims/regctl" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$COPY_ARGUMENTS"
exit "$COPY_STATUS"
SHIM
cat > "$scratch/shims/aws" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$READBACK_ARGUMENTS"
printf '%s\n' "$READBACK"
exit "$READBACK_STATUS"
SHIM
chmod +x "$scratch/shims/"*
export PATH="$scratch/shims:$PATH"
export REGCTL="$scratch/shims/regctl"
export ECR_REGISTRY=registry.example.com ECR_REPO=posthog-cloud
export EXPECTED_DIGEST=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export ORDERED_ALIAS=r000000000002-abcdef
export COPY_ARGUMENTS="$scratch/copy-arguments"
export READBACK_ARGUMENTS="$scratch/readback-arguments"
export TIMEOUT_ARGUMENTS="$scratch/timeout-arguments"
export GITHUB_OUTPUT="$scratch/output"

check() {
    local expected="$1"
    export COPY_STATUS="${2:-0}" READBACK_STATUS="${3:-0}" READBACK="${4:-$EXPECTED_DIGEST}"
    : > "$GITHUB_OUTPUT"
    : > "$COPY_ARGUMENTS"
    : > "$READBACK_ARGUMENTS"
    : > "$TIMEOUT_ARGUMENTS"
    bash "$helper" publish > "$scratch/annotations"
    grep -Fxq -e 'imageTag='"$ORDERED_ALIAS" "$READBACK_ARGUMENTS"
    grep -A1 -Fx -- '--repository-name' "$READBACK_ARGUMENTS" | grep -Fxq "$ECR_REPO"
    grep -A1 -Fx -- '--registry-id' "$READBACK_ARGUMENTS" | grep -Fxq "${ECR_REGISTRY%%.*}"
    test "$(cat "$GITHUB_OUTPUT")" = "outcome=$expected"
    test "$(cat "$TIMEOUT_ARGUMENTS")" = "$(printf '%s\n' --foreground --kill-after=5s "${COPY_TIMEOUT_SECONDS:-40}s" --foreground --kill-after=5s "${READBACK_TIMEOUT_SECONDS:-40}s")"
    case "$expected" in
        present-at-expected-digest) grep -q '::notice title=Ordered image alias present::' "$scratch/annotations" ;;
        absent) grep -q '::warning title=Ordered image alias absent::' "$scratch/annotations" ;;
        integrity-mismatch) grep -q '::error title=Ordered image alias integrity mismatch::' "$scratch/annotations" ;;
        unknown) grep -q '::error title=Ordered image alias read-back unavailable::' "$scratch/annotations" ;;
    esac
    echo "PASS $expected copy=$COPY_STATUS readback=$READBACK_STATUS"
}
check present-at-expected-digest
check present-at-expected-digest 1
check present-at-expected-digest 124
check absent 0 0 None
check integrity-mismatch 0 0 sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
check unknown 0 1
check unknown 0 0 invalid

check_read() {
    local expected="$1" read_status="$2" expected_status="$3" value="$4" status=0
    export READBACK_STATUS="$read_status" READBACK="$value"
    : > "$GITHUB_OUTPUT"
    : > "$COPY_ARGUMENTS"
    : > "$TIMEOUT_ARGUMENTS"
    bash "$helper" read > "$scratch/read-digest" 2> "$scratch/read-error" || status=$?
    test "$status" = "$expected_status"
    test "$(cat "$scratch/read-digest")" = "$value"
    test "$(cat "$GITHUB_OUTPUT")" = "outcome=$expected"
    test ! -s "$COPY_ARGUMENTS"
    test "$(cat "$TIMEOUT_ARGUMENTS")" = "$(printf '%s\n' --foreground --kill-after=5s "${READBACK_TIMEOUT_SECONDS:-40}s")"
    grep -Fxq -e 'imageTag='"$ORDERED_ALIAS" "$READBACK_ARGUMENTS"
    echo "PASS read $expected status=$status"
}
check_read present-at-expected-digest 0 0 "$EXPECTED_DIGEST"
check_read absent 0 0 None
check_read integrity-mismatch 0 0 sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
check_read unknown 1 1 "$EXPECTED_DIGEST"
check_read unknown 0 1 invalid
export COPY_TIMEOUT_SECONDS=120 READBACK_TIMEOUT_SECONDS=30
check present-at-expected-digest
check_read present-at-expected-digest 0 0 "$EXPECTED_DIGEST"
for variable in COPY_TIMEOUT_SECONDS READBACK_TIMEOUT_SECONDS; do
    for invalid in 0 -1 1s invalid 1000; do
        : > "$GITHUB_OUTPUT"
        : > "$TIMEOUT_ARGUMENTS"
        if env "$variable=$invalid" bash "$helper" publish > "$scratch/invalid-timeout" 2>&1; then
            echo "FAIL invalid $variable=$invalid was accepted" >&2
            exit 1
        fi
        test ! -s "$GITHUB_OUTPUT"
        test ! -s "$TIMEOUT_ARGUMENTS"
        grep -Fq 'Invalid ordered image publication timeout' "$scratch/invalid-timeout"
    done
done
for variable in ECR_REGISTRY ECR_REPO ORDERED_ALIAS; do
    : > "$GITHUB_OUTPUT"
    : > "$TIMEOUT_ARGUMENTS"
    if env "$variable=" bash "$helper" read > "$scratch/invalid-read" 2>&1; then
        echo "FAIL read accepted empty $variable" >&2
        exit 1
    fi
    test ! -s "$GITHUB_OUTPUT"
    test ! -s "$TIMEOUT_ARGUMENTS"
    grep -Fq 'requires a registry, repository and alias' "$scratch/invalid-read"
done
: > "$GITHUB_OUTPUT"
: > "$TIMEOUT_ARGUMENTS"
if env READBACK_TIMEOUT_SECONDS=0 bash "$helper" read > "$scratch/invalid-read" 2>&1; then
    echo 'FAIL read accepted an invalid timeout' >&2
    exit 1
fi
test ! -s "$GITHUB_OUTPUT"
test ! -s "$TIMEOUT_ARGUMENTS"
grep -Fq 'Invalid ordered image publication timeout' "$scratch/invalid-read"
echo 'PASS read rejects missing coordinates and invalid timeout before AWS'
unset COPY_TIMEOUT_SECONDS READBACK_TIMEOUT_SECONDS
export SOURCE_REGISTRY=source.example.com SOURCE_REPO=build/image
check present-at-expected-digest
grep -Fxq "source.example.com/build/image@$EXPECTED_DIGEST" "$COPY_ARGUMENTS"
grep -Fxq "registry.example.com/posthog-cloud:$ORDERED_ALIAS" "$COPY_ARGUMENTS"
echo 'PASS separate source and destination coordinates'

check_skip() {
    local variable="$1" title="$2"
    : > "$GITHUB_OUTPUT"
    : > "$COPY_ARGUMENTS"
    : > "$READBACK_ARGUMENTS"
    env "$variable=" bash "$helper" publish > "$scratch/annotations"
    test ! -s "$GITHUB_OUTPUT"
    test ! -s "$COPY_ARGUMENTS"
    test ! -s "$READBACK_ARGUMENTS"
    grep -q "::warning title=$title::" "$scratch/annotations"
    echo "PASS empty $variable skips publication"
}
check_skip EXPECTED_DIGEST 'Ordered image alias source digest unavailable'
check_skip ECR_REGISTRY 'Ordered image alias destination unavailable'
check_skip ECR_REPO 'Ordered image alias destination unavailable'
check_skip REGCTL 'Ordered image alias copy client unavailable'
check_skip SOURCE_REGISTRY 'Ordered image alias source unavailable'
check_skip SOURCE_REPO 'Ordered image alias source unavailable'
unset SOURCE_REGISTRY SOURCE_REPO

cat > "$scratch/shims/curl" <<'SHIM'
#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then
        printf 'incorrect client bytes\n' > "$2"
        exit 0
    fi
    shift
done
exit 1
SHIM
cat > "$scratch/shims/uname" <<'SHIM'
#!/usr/bin/env bash
case "$1" in -s) echo Linux ;; -m) echo x86_64 ;; *) exit 1 ;; esac
SHIM
chmod +x "$scratch/shims/curl" "$scratch/shims/uname"
if bash "$helper" install "$scratch/invalid-regctl" > "$scratch/install" 2>&1; then
    echo 'FAIL corrupt client passed checksum verification' >&2
    exit 1
fi
test ! -x "$scratch/invalid-regctl"
grep -q 'FAILED' "$scratch/install"
echo 'PASS corrupt client fails checksum verification before execution'
rm "$scratch/shims/uname"

mkdir "$scratch/executing"
git -C "$scratch/executing" init -q -b main
git -C "$scratch/executing" config user.name Fixture
git -C "$scratch/executing" config user.email fixture@example.invalid
printf 'base\n' > "$scratch/executing/base"
git -C "$scratch/executing" add base
git -C "$scratch/executing" -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -qm base
git clone -q "$scratch/executing" "$scratch/mirror"
git -C "$scratch/executing" checkout -qb feature
printf 'feature\n' > "$scratch/executing/feature.py"
git -C "$scratch/executing" add feature.py
git -C "$scratch/executing" -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -qm feature
git -C "$scratch/executing" checkout -q main
printf 'relevant\n' > "$scratch/executing/worker.py"
git -C "$scratch/executing" add worker.py
git -C "$scratch/executing" -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -qm relevant
git -C "$scratch/executing" -c core.hooksPath=/dev/null -c commit.gpgsign=false merge -q --no-ff feature -m merge
GITHUB_SHA="$(git -C "$scratch/executing" rev-parse HEAD)"
export GITHUB_SHA
export GITHUB_REF=refs/heads/main GITHUB_REF_NAME=main
test "$(git -C "$scratch/executing" rev-list --first-parent --count HEAD)" = 3
test "$(git -C "$scratch/executing" rev-list --count HEAD)" = 4
: > "$GITHUB_OUTPUT"
(cd "$scratch/executing" && bash "$helper" tag)
executing_tag="$(cat "$GITHUB_OUTPUT")"
test "$executing_tag" = "tag=r000000000003-${GITHUB_SHA:0:6}"
export ORDERED_ALIAS="${executing_tag#tag=}"
check present-at-expected-digest
echo 'PASS merged history uses first-parent ordinal 3 rather than full count 4'
git -C "$scratch/mirror" fetch -q origin main
git -C "$scratch/mirror" -c advice.detachedHead=false checkout -q --detach "$GITHUB_SHA"
: > "$GITHUB_OUTPUT"
(cd "$scratch/mirror" && bash "$helper" tag)
test "$(cat "$GITHUB_OUTPUT")" = "$executing_tag"
echo 'PASS two clones of one history preserve first-parent ordinal and tag'
git clone -q --depth 1 "file://$scratch/executing" "$scratch/shallow"
test "$(git -C "$scratch/shallow" rev-parse --is-shallow-repository)" = true
test "$(git -C "$scratch/shallow" rev-list --first-parent --count HEAD)" = 1
: > "$GITHUB_OUTPUT"
(cd "$scratch/shallow" && bash "$helper" tag)
test "$(git -C "$scratch/shallow" rev-parse --is-shallow-repository)" = false
test "$(cat "$GITHUB_OUTPUT")" = "$executing_tag"
echo 'PASS shallow checkout fetches its configured origin and recovers first-parent ordinal'
export REAL_GIT
REAL_GIT="$(command -v git)"
export FETCH_CALLS="$scratch/fetch-calls" FETCH_RETRY_DELAYS_SECONDS='0 0'
cat > "$scratch/shims/git" <<'SHIM'
#!/usr/bin/env bash
if [ "$1" = fetch ]; then
    calls="$(cat "$FETCH_CALLS")"
    calls=$((calls + 1))
    printf '%s\n' "$calls" > "$FETCH_CALLS"
    if [ "$calls" -le "$FETCH_FAILURES" ]; then
        if [ "${COMPLETE_FAILED_FETCH:-0}" = 1 ]; then "$REAL_GIT" "$@"; fi
        exit "$((120 + calls))"
    fi
fi
exec "$REAL_GIT" "$@"
SHIM
chmod +x "$scratch/shims/git"

check_fetch_timeouts() {
    awk -v attempts="$1" -v maximum="$2" '
        NR % 2 == 1 { if ($0 != "--kill-after=10s") exit 1; next }
        $0 !~ /^[1-9][0-9]*s$/ { exit 1 }
        { sub(/s$/, ""); if ($0 + 0 > maximum + 0) exit 1 }
        END { if (NR != 2 * attempts) exit 1 }
    ' "$TIMEOUT_ARGUMENTS"
}

printf '%s\n' --kill-after=10s 9s > "$TIMEOUT_ARGUMENTS"
check_fetch_timeouts 1 10
printf '%s\n' --kill-after=10s 100s > "$TIMEOUT_ARGUMENTS"
if check_fetch_timeouts 1 90; then
    echo 'FAIL fetch timeout assertion accepted an oversized limit' >&2
    exit 1
fi
echo 'PASS fetch timeout assertions compare seconds numerically'

for failures in 2 3; do
    git clone -q --depth 1 "file://$scratch/executing" "$scratch/retry-$failures"
    export FETCH_FAILURES="$failures"
    printf '0\n' > "$FETCH_CALLS"
    : > "$GITHUB_OUTPUT"
    : > "$TIMEOUT_ARGUMENTS"
    (cd "$scratch/retry-$failures" && bash "$helper" tag) > "$scratch/retry-annotations"
    test "$(cat "$FETCH_CALLS")" = 3
    test "$(grep -c '^::notice ' "$scratch/retry-annotations")" = 2
    grep -Fq 'attempt 1 of 3 failed (status 121); retrying in 0 seconds.' "$scratch/retry-annotations"
    grep -Fq 'attempt 2 of 3 failed (status 122); retrying in 0 seconds.' "$scratch/retry-annotations"
    check_fetch_timeouts 3 90
    if [ "$failures" -eq 2 ]; then
        test "$(cat "$GITHUB_OUTPUT")" = "$executing_tag"
        test "$(git -C "$scratch/retry-$failures" rev-parse --is-shallow-repository)" = false
        if grep -q '^::warning ' "$scratch/retry-annotations"; then exit 1; fi
        echo 'PASS tag retries two failed fetches and succeeds with two notices'
    else
        test ! -s "$GITHUB_OUTPUT"
        grep -Fxq '::warning title=Ordered release tag skipped::Source history could not be fetched (status 123).' "$scratch/retry-annotations"
        echo 'PASS tag stops after three failed fetches with the last status and no tag'
    fi
done
for failures in 2 0; do
    git clone -q --depth 1 "file://$scratch/executing" "$scratch/budget-$failures"
    printf '0\n' > "$FETCH_CALLS"
    : > "$GITHUB_OUTPUT"
    : > "$TIMEOUT_ARGUMENTS"
    (cd "$scratch/budget-$failures" && FETCH_FAILURES="$failures" FETCH_TOTAL_TIMEOUT_SECONDS=20 \
        FETCH_RETRY_DELAYS_SECONDS='8 0' bash "$helper" tag) > "$scratch/budget-annotations"
    test "$(cat "$FETCH_CALLS")" = 1
    check_fetch_timeouts 1 10
    if [ "$failures" -gt 0 ]; then
        test ! -s "$GITHUB_OUTPUT"
        grep -Fxq '::warning title=Ordered release tag skipped::Source history could not be fetched (status 121).' "$scratch/budget-annotations"
        if grep -q '^::notice ' "$scratch/budget-annotations"; then exit 1; fi
        echo 'PASS tag skips a retry that cannot fit the total fetch budget and warns'
    else
        test "$(cat "$GITHUB_OUTPUT")" = "$executing_tag"
        test ! -s "$scratch/budget-annotations"
        echo 'PASS tag shortens its attempt timeout to fit the total fetch budget'
    fi
done
git clone -q --depth 1 "file://$scratch/executing" "$scratch/no-attempt"
printf '0\n' > "$FETCH_CALLS"
: > "$GITHUB_OUTPUT"
: > "$TIMEOUT_ARGUMENTS"
(cd "$scratch/no-attempt" && FETCH_TOTAL_TIMEOUT_SECONDS=10 \
    FETCH_RETRY_DELAYS_SECONDS='0 0' bash "$helper" tag) > "$scratch/no-attempt-annotations"
test "$(cat "$FETCH_CALLS")" = 0
test ! -s "$TIMEOUT_ARGUMENTS"
test ! -s "$GITHUB_OUTPUT"
grep -Fxq '::warning title=Ordered release tag skipped::Complete source history is unavailable.' "$scratch/no-attempt-annotations"
echo 'PASS tag warns without invoking timeout or fetching when no useful attempt fits'
for delays in '21 0' '0 21'; do
    printf '0\n' > "$FETCH_CALLS"
    : > "$GITHUB_OUTPUT"
    : > "$TIMEOUT_ARGUMENTS"
    if (cd "$scratch/executing" && FETCH_TOTAL_TIMEOUT_SECONDS=20 \
        FETCH_RETRY_DELAYS_SECONDS="$delays" bash "$helper" tag) > "$scratch/invalid-fetch-budget" 2>&1; then
        echo 'FAIL tag accepted a retry wait beyond its total budget' >&2
        exit 1
    fi
    test "$(cat "$FETCH_CALLS")" = 0
    test ! -s "$GITHUB_OUTPUT"
    test ! -s "$TIMEOUT_ARGUMENTS"
    grep -Fq 'Invalid ordered source fetch retry delays' "$scratch/invalid-fetch-budget"
done
echo 'PASS tag rejects either retry wait beyond the total fetch budget'
printf '0\n' > "$FETCH_CALLS"
: > "$GITHUB_OUTPUT"
: > "$TIMEOUT_ARGUMENTS"
(cd "$scratch/executing" && bash "$helper" tag) > "$scratch/retry-annotations"
test "$(cat "$FETCH_CALLS")" = 0
test ! -s "$TIMEOUT_ARGUMENTS"
test ! -s "$scratch/retry-annotations"
test "$(cat "$GITHUB_OUTPUT")" = "$executing_tag"
echo 'PASS complete checkout generates a tag without fetching'
git clone -q --depth 1 "file://$scratch/executing" "$scratch/completed-fetch"
printf '0\n' > "$FETCH_CALLS"
: > "$GITHUB_OUTPUT"
(cd "$scratch/completed-fetch" && COMPLETE_FAILED_FETCH=1 bash "$helper" tag) > "$scratch/retry-annotations"
test "$(cat "$FETCH_CALLS")" = 1
test "$(cat "$GITHUB_OUTPUT")" = "$executing_tag"
test "$(grep -c '^::notice ' "$scratch/retry-annotations")" = 1
echo 'PASS tag rechecks shallow state after a failed fetch completes history'
rm "$scratch/shims/git"
unset FETCH_RETRY_DELAYS_SECONDS
GITHUB_SHA="$(git -C "$scratch/mirror" rev-parse HEAD^1)"
git -C "$scratch/mirror" cat-file -e "$GITHUB_SHA^{commit}"
test "$GITHUB_SHA" != "$(git -C "$scratch/mirror" rev-parse HEAD)"
: > "$GITHUB_OUTPUT"
(cd "$scratch/mirror" && bash "$helper" tag) > "$scratch/wrong-checkout"
test ! -s "$GITHUB_OUTPUT"
grep -Fq 'The checked-out revision does not match GITHUB_SHA.' "$scratch/wrong-checkout"
echo 'PASS available built revision that differs from HEAD produces no tag'
export GITHUB_SHA=ffffffffffffffffffffffffffffffffffffffff
: > "$GITHUB_OUTPUT"
(cd "$scratch/mirror" && bash "$helper" tag) > "$scratch/missing"
test ! -s "$GITHUB_OUTPUT"
grep -q '::warning title=Ordered release tag skipped::' "$scratch/missing"
echo 'PASS unavailable built revision is explicit and produces no tag'

has_gnu_timeout() {
    timeout --version 2>/dev/null | grep -Fq 'GNU coreutils'
}

check_standalone_timeout() {
    local client="$1" started="$SECONDS" elapsed pid
    : > "$GITHUB_OUTPUT"
    : > "$scratch/standalone-processes"
    PATH="$scratch/standalone:$system_path" REGCTL="$scratch/standalone/regctl" \
        COPY_TIMEOUT_SECONDS=1 READBACK_TIMEOUT_SECONDS=1 HUNG_CLIENT="$client" \
        HUNG_PID="$scratch/hung-pid" HUNG_PIPE="$scratch/hung-pipe" \
        COMPLETION_MARKER="$scratch/standalone-completed" PROCESS_IDENTITIES="$scratch/standalone-processes" \
        bash "$helper" publish > "$scratch/standalone-annotations" 2> "$scratch/standalone-error"
    elapsed=$((SECONDS - started))
    pid="$(cat "$scratch/hung-pid")"
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid"
        echo "FAIL standalone $client survived its timeout" >&2
        return 1
    fi
    test ! -e "$scratch/standalone-completed"
    if [ "$client" = regctl ]; then
        grep -Fq 'publication exited with status 137' "$scratch/standalone-annotations"
        grep -Fxq 'outcome=absent' "$GITHUB_OUTPUT"
    else
        grep -Fxq 'outcome=unknown' "$GITHUB_OUTPUT"
    fi
    test "$(wc -l < "$scratch/standalone-processes" | tr -d ' ')" = 2
    cat "$scratch/standalone-processes"
    echo "PASS standalone $client deadline_ms=1000 kill_after_ms=5000 elapsed_seconds=$elapsed completed=false"
}

if PATH="$system_path" has_gnu_timeout; then
    mkdir "$scratch/standalone"
    mkfifo "$scratch/hung-pipe"
    cat > "$scratch/standalone/client" <<'CLIENT'
#!/usr/bin/env bash
case "$(ps -p "$PPID" -o comm=)" in *timeout) ;; *) exit 1 ;; esac
printf '%s pid=%s timeout_pid=%s\n' "${0##*/}" "$$" "$PPID" >> "$PROCESS_IDENTITIES"
if [ "${0##*/}" = "$HUNG_CLIENT" ]; then
    trap '' TERM
    printf '%s\n' "$$" > "$HUNG_PID"
    exec 3<>"$HUNG_PIPE"
    read -r -t 15 -u 3 || true
    printf completed > "$COMPLETION_MARKER"
fi
if [ "${0##*/}" = aws ]; then printf 'None\n'; fi
CLIENT
    chmod +x "$scratch/standalone/client"
    ln -s client "$scratch/standalone/regctl"
    ln -s client "$scratch/standalone/aws"
    check_standalone_timeout regctl
    check_standalone_timeout aws
else
    echo 'SKIP standalone helper timeouts: GNU coreutils timeout is unavailable'
fi
