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
export GITHUB_OUTPUT="$scratch/output"

check() {
    local expected="$1"
    : > "$GITHUB_OUTPUT"
    bash "$helper" publish > "$scratch/annotations"
    test "$(cat "$GITHUB_OUTPUT")" = "outcome=$expected"
    case "$expected" in
        present-at-expected-digest) grep -q '::notice title=Ordered image alias present::' "$scratch/annotations" ;;
        absent) grep -q '::warning title=Ordered image alias absent::' "$scratch/annotations" ;;
        integrity-mismatch) grep -q '::error title=Ordered image alias integrity mismatch::' "$scratch/annotations" ;;
        unknown) grep -q '::error title=Ordered image alias read-back unavailable::' "$scratch/annotations" ;;
    esac
    echo "PASS $expected copy=$COPY_STATUS readback=$READBACK_STATUS"
}
export COPY_STATUS=0 READBACK_STATUS=0 READBACK="$EXPECTED_DIGEST"
check present-at-expected-digest
export COPY_STATUS=1
check present-at-expected-digest
export COPY_STATUS=124
check present-at-expected-digest
export READBACK=None
check absent
export READBACK=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
check integrity-mismatch
export READBACK_STATUS=1
check unknown
export READBACK_STATUS=0 READBACK=invalid
check unknown
export SOURCE_REGISTRY=source.example.com SOURCE_REPO=build/image READBACK="$EXPECTED_DIGEST"
check present-at-expected-digest
grep -Fxq "source.example.com/build/image@$EXPECTED_DIGEST" "$COPY_ARGUMENTS"
grep -Fxq "registry.example.com/posthog-cloud:$ORDERED_ALIAS" "$COPY_ARGUMENTS"
echo 'PASS separate source and destination coordinates'

mkdir "$scratch/executing"
git -C "$scratch/executing" init -q -b main
git -C "$scratch/executing" config user.name Fixture
git -C "$scratch/executing" config user.email fixture@example.invalid
printf 'base\n' > "$scratch/executing/base"
git -C "$scratch/executing" add base
git -C "$scratch/executing" -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -qm base
git clone -q "$scratch/executing" "$scratch/public"
printf 'relevant\n' > "$scratch/executing/worker.py"
git -C "$scratch/executing" add worker.py
git -C "$scratch/executing" -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -qm relevant
export GITHUB_SHA="$(git -C "$scratch/executing" rev-parse HEAD)"
export GITHUB_REF=refs/heads/main GITHUB_REF_NAME=main GITHUB_REPOSITORY=PostHog/posthog-private
: > "$GITHUB_OUTPUT"
(cd "$scratch/executing" && bash "$helper" tag)
private_tag="$(cat "$GITHUB_OUTPUT")"
test "$private_tag" = "tag=r000000000002-${GITHUB_SHA:0:6}"
export ORDERED_ALIAS="${private_tag#tag=}"
check present-at-expected-digest
echo 'PASS relevant executing-only revision supplies its publication identity'
git -C "$scratch/public" fetch -q origin main
git -C "$scratch/public" -c advice.detachedHead=false checkout -q --detach "$GITHUB_SHA"
export GITHUB_REPOSITORY=PostHog/posthog
: > "$GITHUB_OUTPUT"
(cd "$scratch/public" && bash "$helper" tag)
test "$(cat "$GITHUB_OUTPUT")" = "$private_tag"
echo 'PASS later public exposure preserves ordinal and publication identity'
export GITHUB_SHA=ffffffffffffffffffffffffffffffffffffffff
: > "$GITHUB_OUTPUT"
(cd "$scratch/public" && bash "$helper" tag) > "$scratch/missing"
test ! -s "$GITHUB_OUTPUT"
grep -q '::warning title=Ordered release tag skipped::' "$scratch/missing"
echo 'PASS unavailable built revision is explicit and produces no tag'
