#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "$0")/../.." && pwd)"
helper="$repository_root/.github/scripts/ordered-image-release.sh"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
mkdir "$scratch/shims"
cat > "$scratch/shims/timeout" <<'SHIM'
#!/usr/bin/env bash
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
export GITHUB_OUTPUT="$scratch/output"

check() {
    local expected="$1"
    export COPY_STATUS="${2:-0}" READBACK_STATUS="${3:-0}" READBACK="${4:-$EXPECTED_DIGEST}"
    : > "$GITHUB_OUTPUT"
    : > "$COPY_ARGUMENTS"
    : > "$READBACK_ARGUMENTS"
    bash "$helper" publish > "$scratch/annotations"
    grep -Fxq -e 'imageTag='"$ORDERED_ALIAS" "$READBACK_ARGUMENTS"
    grep -A1 -Fx -- '--repository-name' "$READBACK_ARGUMENTS" | grep -Fxq "$ECR_REPO"
    grep -A1 -Fx -- '--registry-id' "$READBACK_ARGUMENTS" | grep -Fxq "${ECR_REGISTRY%%.*}"
    test "$(cat "$GITHUB_OUTPUT")" = "outcome=$expected"
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
chmod +x "$scratch/shims/curl"
if bash "$helper" install "$scratch/invalid-regctl" > "$scratch/install" 2>&1; then
    echo 'FAIL corrupt client passed checksum verification' >&2
    exit 1
fi
test ! -x "$scratch/invalid-regctl"
grep -q 'FAILED' "$scratch/install"
echo 'PASS corrupt client fails checksum verification before execution'

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
