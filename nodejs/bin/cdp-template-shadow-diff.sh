#!/usr/bin/env bash
# Records the requests every CDP template sends on a base ref and on the working tree, then diffs them per template.
#
# Usage: nodejs/bin/cdp-template-shadow-diff.sh [base-ref]
#   base-ref                  defaults to the merge base of HEAD and origin/master
#   CDP_TEMPLATE_CORPUS       JSON corpus to run on, defaults to the invented corpus
#   CDP_TEMPLATE_SHADOW_DIR   where the two recordings go, defaults to a new temp directory
#
# The base checkout runs with this tree's node_modules and recorder files, so a dependency change is not part of the diff.
# Exits 0 when every template sends the same requests, 1 when any differ.
set -euo pipefail

nodejs_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$nodejs_dir/.." && pwd)"
base_ref="${1:-$(git -C "$repo_root" merge-base HEAD origin/master)}"
shadow_dir="${CDP_TEMPLATE_SHADOW_DIR:-$(mktemp -d)}"
base_tree="$(mktemp -d)/base"
corpus="${CDP_TEMPLATE_CORPUS:+$(realpath "$CDP_TEMPLATE_CORPUS")}"

recorder_files=(
    src/cdp/templates/test/template-pipeline.ts
    src/cdp/templates/test/shadow-recording.ts
    src/cdp/templates/test/template-outputs.recording.ts
    src/cdp/templates/test/corpus/invented-events.json
)

remove_base_tree() {
    git -C "$repo_root" worktree remove --force "$base_tree" >/dev/null 2>&1 || true
    rm -rf "$(dirname "$base_tree")"
}
trap remove_base_tree EXIT

prepare_base_tree() {
    # Hooks off: the post-checkout hook would install a second node_modules into the throwaway checkout.
    git -C "$repo_root" -c core.hooksPath=/dev/null worktree add --detach --quiet "$base_tree" "$base_ref"
    ln -s "$repo_root/node_modules" "$base_tree/node_modules"
    ln -s "$nodejs_dir/node_modules" "$base_tree/nodejs/node_modules"
    for file in "${recorder_files[@]}"; do
        mkdir -p "$(dirname "$base_tree/nodejs/$file")"
        cp "$nodejs_dir/$file" "$base_tree/nodejs/$file"
    done
    cp --update=none "$nodejs_dir"/tests/fixtures/hog-bytecode/*.json "$base_tree/nodejs/tests/fixtures/hog-bytecode/"
}

record() {
    local checkout="$1" output="$2"
    rm -rf "$output"
    if ! (cd "$checkout" && CDP_TEMPLATE_RECORDING_DIR="$output" CDP_TEMPLATE_CORPUS="$corpus" pnpm exec jest \
        --config jest.config.js --testMatch '<rootDir>/src/cdp/templates/test/*.recording.ts' >"$output.log" 2>&1); then
        echo "Recording failed in $checkout. Last lines of $output.log:" >&2
        tail -40 "$output.log" >&2
        exit 2
    fi
}

mkdir -p "$shadow_dir"
echo "Recording $(git -C "$repo_root" rev-parse --short "$base_ref") (base) and the working tree into $shadow_dir" >&2
prepare_base_tree
record "$base_tree/nodejs" "$shadow_dir/base"
record "$nodejs_dir" "$shadow_dir/head"

if git --no-pager diff --no-index --stat "$shadow_dir/base" "$shadow_dir/head"; then
    echo "No differences: every template sends the same requests on base and the working tree." >&2
    exit 0
fi
git --no-pager diff --no-index "$shadow_dir/base" "$shadow_dir/head" || true
exit 1
