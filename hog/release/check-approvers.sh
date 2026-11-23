#!/usr/bin/env bash
# Usage: check-approvers.sh [--extra-paths <file>] <first commit> <last commit> <approver>...
#        check-approvers.sh --report [--extra-paths <file>] <first commit> <last commit>
#        check-approvers.sh --list-paths
#
# The owners of a release are the people who opened, merged or wrote commits in a pull request that
# changed anything under RELEASE_PATHS between the two commits: the hog changesets, and the trees hog
# compiles in, whose changes ship whether or not a changeset names them. --extra-paths names more
# paths, one plain path per line, whose pull requests also own the release. The release workflow passes
# what it builds from, which can grow before a release tag carries a longer RELEASE_PATHS. The extra
# paths only add owners, so the caller can't use them to clear anyone. The check fails when an
# approver is one of the owners, and writes `violations=<who (#pull requests)>` to GITHUB_OUTPUT.
# --report checks nobody and writes the pull requests and their owners as Slack mrkdwn instead, as
# `prs_mrkdwn` and `owners_mrkdwn`. --list-paths prints RELEASE_PATHS, one per line, and changes nothing:
# the release workflow only warns when they miss something the release builds, because the extra paths
# it passes already make those pull requests owners. Every lookup that fails stops the
# script, because a check that can't run can't clear anyone.
#
# Needs GH_TOKEN and REPOSITORY, and the history of both commits in the checkout.
set -euo pipefail

# Everything the release build reads from the release commit: every tree the hog and CLI library builds
# compile in, the workspace packages and dependency files pnpm installs from, the local actions and the
# workflow that run the build, and more. All of hog/ counts, which holds the changesets, this script and
# catalog-gap.ts. The list lives here rather than coming from a build, because the release workflow runs
# this script as the last release tag has it, so a pull request can't narrow it for its own release.
# Counting too much only blocks more approvers: many people change pnpm-lock.yaml each week, and each of
# them is one more person who can't approve that week's release.
RELEASE_PATHS=(
    'hog'
    'services/mcp'
    ':(glob)products/*/mcp/**'
    'products/notebooks'
    'products/posthog_ai/skills/querying-posthog-data/references/guidelines.md'
    'products/ai_observability/backend/prompts/parser_recipe_examples.yaml'
    'tools/openapi-codegen'
    'packages/llm-normalizer'
    'packages/quill'
    'package.json'
    'pnpm-lock.yaml'
    'pnpm-workspace.yaml'
    '.npmrc'
    '.pnpmfile.cjs'
    '.nvmrc'
    'patches'
    '.husky'
    'bin/fix-rdkafka-paths'
    '.github/actions/pnpm-install'
    '.github/actions/setup-pnpm'
    '.github/workflows/release-hog.yml'
)

if [ "${1:-}" = --list-paths ]; then
    printf '%s\n' "${RELEASE_PATHS[@]}"
    exit 0
fi

report=false
paths=("${RELEASE_PATHS[@]}")
while [ "$#" -gt 0 ]; do
    case $1 in
        --report)
            report=true
            shift
            ;;
        --extra-paths)
            # Each line names a path literally, so a glob or a pathspec magic word in it matches nothing
            # else. Anything but a plain relative path stops the check.
            while IFS= read -r path || [ -n "$path" ]; do
                [ -z "$path" ] && continue
                if ! [[ "$path" =~ ^[A-Za-z0-9._@+-][A-Za-z0-9._@+/-]*$ ]] || [[ "/$path/" == */../* ]]; then
                    echo "::error::$2 holds a line that isn't a plain relative path: $path"
                    exit 1
                fi
                paths+=(":(literal)$path")
            done <"$2"
            shift 2
            ;;
        *) break ;;
    esac
done
base=$1
head=$2
shift 2
if [ "$report" = false ] && [ "$#" -eq 0 ]; then
    echo "::error::No approvers to check"
    exit 1
fi

for approver in "$@"; do
    if [ -z "$approver" ]; then
        echo "::error::An approver login is empty"
        exit 1
    fi
done
if ! git merge-base --is-ancestor "$base" "$head"; then
    echo "::error::$base isn't an ancestor of $head, so the range of released commits is unknown"
    exit 1
fi

# Without rename detection, a file that moves into one of the paths counts as added there.
commits=$(git log --no-renames --format=%H "$base..$head" -- "${paths[@]}")
shas=()
if [ -n "$commits" ]; then
    mapfile -t shas <<<"$commits"
fi

# One GraphQL query per 10 commits returns each commit's merged pull request with its author and
# merger, which commits/{sha}/pulls leaves out, and the accounts the commit credits, Co-authored-by
# trailers included. Larger batches pass GitHub's 10-second query limit on this repository, and a 502
# or timeout gets two more tries.
owner=${REPOSITORY%%/*}
name=${REPOSITORY#*/}
people=""
numbers=""
titles=""
for ((i = 0; i < ${#shas[@]}; i += 10)); do
    fields=""
    for sha in "${shas[@]:i:10}"; do
        fields+="c$sha: object(oid: \"$sha\") { ... on Commit { authors(first: 50) { totalCount nodes { user { login } } } associatedPullRequests(first: 10) { nodes { number title merged author { login __typename } mergedBy { login __typename } } } } } "
    done
    for attempt in 1 2 3; do
        if response=$(gh api graphql -f query="query { repository(owner: \"$owner\", name: \"$name\") { $fields } }"); then
            break
        fi
        if [ "$attempt" -eq 3 ]; then
            echo "::error::GitHub couldn't list the pull requests of the released commits"
            exit 1
        fi
        sleep $((attempt * 5))
    done
    if [ "$(jq '.errors // [] | length' <<<"$response")" -ne 0 ]; then
        echo "::error::GitHub couldn't list the pull requests of the released commits"
        jq -c '.errors' <<<"$response"
        exit 1
    fi

    unlinked=$(jq -r '.data.repository | to_entries[] | select([.value.associatedPullRequests.nodes[]? | select(.merged)] | length == 0) | .key | ltrimstr("c")' <<<"$response")
    if [ -n "$unlinked" ]; then
        echo "::error::These released commits have no merged pull request, so their authors can't be ruled out:"
        printf '%s\n' "$unlinked"
        exit 1
    fi
    crowded=$(jq -r '.data.repository | to_entries[] | select(.value.authors.totalCount > (.value.authors.nodes | length)) | .key | ltrimstr("c")' <<<"$response")
    if [ -n "$crowded" ]; then
        echo "::error::These released commits credit more authors than one query lists, so their authors can't be ruled out:"
        printf '%s\n' "$crowded"
        exit 1
    fi

    people+=$(jq -r '.data.repository[] | . as $commit | .associatedPullRequests.nodes[] | select(.merged) | .number as $n
        | (if .author.__typename == "Bot" then empty else ($n | tostring) + "\t" + (.author.login // "") end),
          (if .mergedBy.__typename == "Bot" then empty else ($n | tostring) + "\t" + (.mergedBy.login // "") end),
          ($commit.authors.nodes[] | ($n | tostring) + "\t" + (.user.login // ""))' <<<"$response")
    people+=$'\n'
    titles+=$(jq -r '.data.repository[].associatedPullRequests.nodes[] | select(.merged) | "\(.number)\t\(.title)"' <<<"$response")
    titles+=$'\n'
    numbers+=$(jq -r '.data.repository[].associatedPullRequests.nodes[] | select(.merged) | .number' <<<"$response")
    numbers+=$'\n'
done

# A squash merge credits the opener, and its trailers name only the authors GitHub matched when it
# merged, so anyone who pushed to someone else's pull request is also read from its own commits: their
# authors, Co-authored-by trailers included, and committers. An account GitHub can't link to a commit
# email, like an agent's noreply trailer, can't approve anything, so it's left out.
# shellcheck disable=SC2016 # GraphQL variables, not shell ones
pr_query='query($owner: String!, $name: String!, $number: Int!, $endCursor: String) {
    repository(owner: $owner, name: $name) { pullRequest(number: $number) {
        commits(first: 100, after: $endCursor) { pageInfo { hasNextPage endCursor }
            nodes { commit { authors(first: 50) { totalCount nodes { user { login } } } committer { user { login } } } } } } } }'
while read -r number; do
    for attempt in 1 2 3; do
        if logins=$(gh api graphql --paginate -f query="$pr_query" -F owner="$owner" -F name="$name" -F number="$number" \
            --jq '.data.repository.pullRequest.commits.nodes[].commit
                | if .authors.totalCount > (.authors.nodes | length) then "!crowded" else empty end,
                  (.authors.nodes[].user.login // empty), (.committer.user.login // empty)'); then
            break
        fi
        if [ "$attempt" -eq 3 ]; then
            echo "::error::GitHub couldn't list the commits of #$number"
            exit 1
        fi
        sleep $((attempt * 5))
    done
    if grep -qx '!crowded' <<<"$logins"; then
        echo "::error::A commit in #$number credits more authors than one query lists, so its authors can't be ruled out"
        exit 1
    fi
    if [ -n "$logins" ]; then
        people+=$(awk -v n="$number" '{ print n "\t" $0 }' <<<"$logins")
        people+=$'\n'
    fi
done < <(sed '/^$/d' <<<"$numbers" | sort -u)
# Bots, like the merge queue that merges most pull requests, can't approve anything.
people=$(awk -F '\t' '$2 != "" && $2 !~ /\[bot\]$/' <<<"$people" | sort -u)

if [ "$report" = true ]; then
    escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
    prs=$(sort -u -t $'\t' -k1,1n <<<"$titles" | sed '/^$/d' | while IFS=$'\t' read -r number title; do
        printf '<https://github.com/%s/pull/%s|#%s> %s\n' "$REPOSITORY" "$number" "$number" "$(escape <<<"$title")"
    done)
    owners=$(cut -f2 <<<"$people" | sort -u | sed '/^$/d' | while read -r login; do
        numbers=$(awk -F '\t' -v who="$login" '$2 == who { print "#" $1 }' <<<"$people" | sort -u | paste -sd ' ' -)
        printf '<https://github.com/%s|%s> (%s)\n' "$login" "$login" "$numbers"
    done | paste -sd ',' - | sed 's/,/, /g')
    delimiter="report_$(openssl rand -hex 8)"
    {
        echo "prs_mrkdwn<<$delimiter"
        echo "$prs"
        echo "$delimiter"
        echo "owners_mrkdwn=$owners"
    } >>"$GITHUB_OUTPUT"
    echo "The release owners are $owners"
    exit 0
fi

echo "Checked ${#shas[@]} commits in $base..$head against the approvals of $*"

blocked=""
for approver in "$@"; do
    numbers=$(awk -F '\t' -v who="$approver" '$2 == who { print "#" $1 }' <<<"$people" | sort -u | paste -sd ' ' -)
    if [ -n "$numbers" ]; then
        blocked+="${blocked:+, }$approver ($numbers)"
    fi
done
if [ -n "$blocked" ]; then
    echo "violations=$blocked" >>"$GITHUB_OUTPUT"
    echo "::error::These approvers opened, merged or wrote commits in a pull request this release ships: $blocked"
    exit 1
fi
