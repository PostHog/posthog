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
# merger, which commits/{sha}/pulls leaves out. Larger batches pass GitHub's 10-second query limit on
# this repository, and a 502 or timeout gets two more tries.
owner=${REPOSITORY%%/*}
name=${REPOSITORY#*/}
pulls=""
for ((i = 0; i < ${#shas[@]}; i += 10)); do
    fields=""
    for sha in "${shas[@]:i:10}"; do
        fields+="c$sha: object(oid: \"$sha\") { ... on Commit { associatedPullRequests(first: 10) { nodes { number merged author { login } mergedBy { login } commits { totalCount } } } } } "
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

    pulls+=$(jq -r '.data.repository[].associatedPullRequests.nodes[] | select(.merged) | [.number, (.author.login // ""), (.mergedBy.login // ""), .commits.totalCount] | @tsv' <<<"$response")
    pulls+=$'\n'
done

# A squash merge credits only the opener, so anyone who pushed commits to someone else's pull request
# is read from the pull request's own commits. The REST list stops at 250 commits, so a longer pull
# request can't be cleared. Commit authors GitHub can't link to an account, like Co-authored-by
# trailers with an unknown email, can't approve anything, so they're left out.
people=$(awk -F '\t' 'NF { print $1 "\t" $2; print $1 "\t" $3 }' <<<"$pulls")
people+=$'\n'
while read -r number commit_count; do
    if [ "$commit_count" -gt 250 ]; then
        echo "::error::#$number has $commit_count commits, more than GitHub lists, so its commit authors can't be ruled out"
        exit 1
    fi
    for attempt in 1 2 3; do
        if logins=$(gh api "repos/$REPOSITORY/pulls/$number/commits?per_page=100" --paginate \
            --jq '.[] | (.author.login // empty), (.committer.login // empty)'); then
            break
        fi
        if [ "$attempt" -eq 3 ]; then
            echo "::error::GitHub couldn't list the commits of #$number"
            exit 1
        fi
        sleep $((attempt * 5))
    done
    if [ -n "$logins" ]; then
        people+=$(awk -v n="$number" '{ print n "\t" $0 }' <<<"$logins")
        people+=$'\n'
    fi
done < <(awk -F '\t' 'NF { print $1, $4 }' <<<"$pulls" | sort -u)
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
