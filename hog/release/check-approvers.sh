#!/usr/bin/env bash
# Usage: check-approvers.sh <first commit> <last commit> <approver>...
#
# Fails when an approver opened, merged or wrote commits in a pull request that changed a path in
# HOG_SOURCE_PATHS between the two commits, and writes `violations=<who (#pull requests)>` to
# GITHUB_OUTPUT. Every lookup that fails stops the check, because a check that can't run can't clear
# anyone.
#
# Needs GH_TOKEN, REPOSITORY and HOG_SOURCE_PATHS, and the history of both commits in the checkout.
set -euo pipefail

base=$1
head=$2
shift 2
if [ "$#" -eq 0 ]; then
    echo "::error::No approvers to check"
    exit 1
fi

read -ra paths <<<"$HOG_SOURCE_PATHS"
commits=$(git log --format=%H "$base..$head" -- "${paths[@]}")
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
for ((i = 0; i < ${#shas[@]}; i += 10)); do
    fields=""
    for sha in "${shas[@]:i:10}"; do
        fields+="c$sha: object(oid: \"$sha\") { ... on Commit { authors(first: 50) { totalCount nodes { user { login } } } associatedPullRequests(first: 10) { nodes { number merged author { login } mergedBy { login } } } } } "
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
        | ($n | tostring) + "\t" + (.author.login // ""), ($n | tostring) + "\t" + (.mergedBy.login // ""),
          ($commit.authors.nodes[] | ($n | tostring) + "\t" + (.user.login // ""))' <<<"$response")
    people+=$'\n'
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
