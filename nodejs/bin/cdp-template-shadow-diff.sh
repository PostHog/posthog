#!/usr/bin/env bash
# Records the requests every CDP template sends on a base ref and on a head ref, then diffs them per template.
#
# Usage: nodejs/bin/cdp-template-shadow-diff.sh [--handoff] [base-ref [head-ref]]
#   base-ref                  defaults to the merge base of HEAD and origin/master
#   head-ref                  defaults to the working tree
#   --handoff                 each version runs the destination jobs the other version queued, the way old and new
#                             pods share the hog queue during a deploy. A handoff is flagged when it sends what
#                             neither version sends on its own. The comparison fails when a version's own jobs
#                             send something other than its direct recording.
#   CDP_TEMPLATE_CORPUS       JSON corpus to run on, defaults to the invented corpus
#   CDP_TEMPLATE_SHADOW_DIR   where the recordings go, defaults to a new temp directory
#
# Each ref runs with this tree's node_modules and recorder files, so a dependency change is not part of the diff.
# Run it inside the flox environment, so the Kafka client finds its native libraries.
# Exits 0 when every template sends the same requests, 1 when any differ, 2 when the comparison itself fails.
set -Eeuo pipefail
trap 'exit 2' ERR

absolute_path() {
    mkdir -p "$1"
    (cd "$1" && pwd)
}

nodejs_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$nodejs_dir/.." && pwd)"

resolve_ref() {
    git -C "$repo_root" rev-parse --verify --quiet "$1^{commit}" || {
        echo "Unknown ref: $1" >&2
        exit 2
    }
}

handoff=false
if [[ "${1:-}" == "--handoff" ]]; then
    handoff=true
    shift
fi
base_ref="$(resolve_ref "${1:-$(git -C "$repo_root" merge-base HEAD origin/master)}")"
head_ref=""
if [[ -n "${2:-}" ]]; then
    head_ref="$(resolve_ref "$2")"
fi
shadow_dir="$(absolute_path "${CDP_TEMPLATE_SHADOW_DIR:-$(mktemp -d)}")"
checkouts_dir="$(mktemp -d)"
corpus=""
if [[ -n "${CDP_TEMPLATE_CORPUS:-}" ]]; then
    corpus="$(cd "$(dirname "$CDP_TEMPLATE_CORPUS")" && pwd)/$(basename "$CDP_TEMPLATE_CORPUS")"
fi

recorder_files=(
    src/cdp/templates/compiler.ts
    src/cdp/templates/test/template-pipeline.ts
    src/cdp/templates/test/kafka-queue-handoff.ts
    src/cdp/templates/test/shadow-recording.ts
    src/cdp/templates/test/template-outputs.recording.ts
    src/cdp/templates/test/corpus/invented-events.json
)

remove_checkouts() {
    for checkout in "$checkouts_dir"/*; do
        git -C "$repo_root" worktree remove --force "$checkout" >/dev/null 2>&1 || true
    done
    rm -rf "$checkouts_dir"
}
trap remove_checkouts EXIT

prepare_checkout() {
    local name="$1" ref="$2" tree="$checkouts_dir/$1"
    # Hooks off: the post-checkout hook would install a second node_modules into the throwaway checkout.
    git -C "$repo_root" -c core.hooksPath=/dev/null worktree add --detach --quiet "$tree" "$ref"
    ln -s "$repo_root/node_modules" "$tree/node_modules"
    ln -s "$nodejs_dir/node_modules" "$tree/nodejs/node_modules"
    for file in "${recorder_files[@]}"; do
        mkdir -p "$(dirname "$tree/nodejs/$file")"
        cp "$nodejs_dir/$file" "$tree/nodejs/$file"
    done
    local fixture target
    for fixture in "$nodejs_dir"/tests/fixtures/hog-bytecode/*.json; do
        target="$tree/nodejs/tests/fixtures/hog-bytecode/$(basename "$fixture")"
        [[ -e "$target" ]] || cp "$fixture" "$target"
    done
    echo "$tree/nodejs"
}

run_recorder() {
    local checkout="$1" log="$2"
    shift 2
    if ! (cd "$checkout" && env CDP_TEMPLATE_CORPUS="$corpus" "$@" pnpm exec jest \
        --config jest.config.js --testMatch '<rootDir>/src/cdp/templates/test/*.recording.ts' >"$log" 2>&1); then
        echo "Recording failed in $checkout. Last lines of $log:" >&2
        tail -40 "$log" >&2
        exit 2
    fi
}

checkout_of() {
    case "$1" in
        base) echo "$base_checkout" ;;
        head) echo "$head_checkout" ;;
    esac
}

base_checkout="$(prepare_checkout base "$base_ref")"
head_checkout="$nodejs_dir"
head_label="the working tree"
if [[ -n "$head_ref" ]]; then
    head_checkout="$(prepare_checkout head "$head_ref")"
    head_label="$(git -C "$repo_root" rev-parse --short "$head_ref") (head)"
fi
echo "Recording $(git -C "$repo_root" rev-parse --short "$base_ref") (base) and $head_label into $shadow_dir" >&2

compare_versions() {
    for side in base head; do
        rm -rf "${shadow_dir:?}/$side"
        run_recorder "$(checkout_of "$side")" "$shadow_dir/$side.log" CDP_TEMPLATE_RECORDING_DIR="$shadow_dir/$side"
    done

    local diff_status=0
    git --no-pager diff --no-index --stat "$shadow_dir/base" "$shadow_dir/head" || diff_status=$?
    case "$diff_status" in
        0)
            echo "No differences: every template sends the same requests on both versions." >&2
            exit 0
            ;;
        1)
            git --no-pager diff --no-index "$shadow_dir/base" "$shadow_dir/head" || true
            exit 1
            ;;
        *)
            echo "Comparing the recordings failed with status $diff_status." >&2
            exit 2
            ;;
    esac
}

# A same-version handoff that differs from the direct recording means the harness lost something on the way through
# the queue, so every handoff comparison built on it would be meaningless.
check_handoff_fidelity() {
    local side broken=0 handoff_file name
    for side in base head; do
        for handoff_file in "$shadow_dir/$side-to-$side"/*.json; do
            name="$(basename "$handoff_file")"
            if ! cmp -s "$handoff_file" "$shadow_dir/$side/$name"; then
                broken=$((broken + 1))
                echo "Queuing changes what ${name%.json} sends on $side, with no other version involved." >&2
                git --no-pager diff --no-index "$shadow_dir/$side/$name" "$handoff_file" || true
            fi
        done
    done
    if [[ "$broken" -gt 0 ]]; then
        echo "$broken recordings change when queued on one version, so the recorder or that version's queue path is broken." >&2
        exit 2
    fi
}

compare_handoffs() {
    for side in base head; do
        rm -rf "${shadow_dir:?}/$side" "${shadow_dir:?}/jobs-$side"
        run_recorder "$(checkout_of "$side")" "$shadow_dir/$side.log" CDP_TEMPLATE_RECORDING_DIR="$shadow_dir/$side"
        run_recorder "$(checkout_of "$side")" "$shadow_dir/jobs-$side.log" \
            CDP_TEMPLATE_HANDOFF=queue CDP_TEMPLATE_HANDOFF_DIR="$shadow_dir/jobs-$side"
    done
    for producer in base head; do
        for consumer in base head; do
            local recording="$shadow_dir/$producer-to-$consumer"
            rm -rf "$recording"
            run_recorder "$(checkout_of "$consumer")" "$recording.log" CDP_TEMPLATE_HANDOFF=run \
                CDP_TEMPLATE_HANDOFF_DIR="$shadow_dir/jobs-$producer" CDP_TEMPLATE_RECORDING_DIR="$recording"
        done
    done

    check_handoff_fidelity

    local flagged=0
    for direction in "base head" "head base"; do
        local producer consumer
        read -r producer consumer <<<"$direction"
        for handoff_file in "$shadow_dir/$producer-to-$consumer"/*.json; do
            local name producer_file consumer_file
            name="$(basename "$handoff_file")"
            producer_file="$shadow_dir/$producer-to-$producer/$name"
            consumer_file="$shadow_dir/$consumer-to-$consumer/$name"
            if cmp -s "$handoff_file" "$producer_file" || cmp -s "$handoff_file" "$consumer_file"; then
                continue
            fi
            flagged=$((flagged + 1))
            echo "Flagged ${name%.json}: jobs $producer queued send something else when $consumer runs them." >&2
            git --no-pager diff --no-index "$producer_file" "$handoff_file" || true
        done
    done

    if [[ "$flagged" -eq 0 ]]; then
        echo "No differences: every queued job sends the same requests when the other version runs it." >&2
        exit 0
    fi
    echo "$flagged handoffs send what neither version sends on its own. Diffs compare with the queuing version." >&2
    exit 1
}

if [[ "$handoff" == true ]]; then
    compare_handoffs
else
    compare_versions
fi
