#!/usr/bin/env node

// Whether a full Backend CI run already passed on this pull request. turbo-discover then lets
// later pushes run the selected subset instead of the full matrices.
//
// A pass is the gate's Test results check, concluded success with FULL_RUN_EXTERNAL_ID, on any
// head the pull request has had: its current commits, plus the heads that force-pushes replaced.
// The check lives on a commit, not on the branch, so a rebase or a master merge keeps it.
//
// A Trunk merge queue kick for failed tests after the newest pass re-arms full runs, until the
// next full run passes. Trunk reports queue state only in one sticky comment that it rewrites in
// place, so the comment's update time is the kick time.
//
// Input:  GH_TOKEN, GITHUB_REPOSITORY, PR_NUMBER
// Output: key=value lines for GITHUB_OUTPUT on stdout. A failed read exits non-zero and prints
//         nothing, which the workflow reads as "no full pass", so the run stays full.

const { execFileSync } = require('child_process')

const GATE_CHECK_NAME = 'Backend CI on Depot / Test results'
const FULL_RUN_EXTERNAL_ID = 'backend-matrix=full'
const TRUNK_LOGIN = /^trunk-io(\[bot\])?$/
const QUEUE_FAILURE_WORDING = [/removed from the merge queue because it failed tests/, /required check .* has failed/]

const QUERY = `
query ($owner: String!, $name: String!, $number: Int!, $checkName: String!) {
    repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
            commits(last: 100) { nodes { commit { ...gateChecks } } }
            timelineItems(last: 100, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT]) {
                nodes { ... on HeadRefForcePushedEvent { beforeCommit { ...gateChecks } } }
            }
            comments(last: 100) { nodes { author { login } body updatedAt } }
        }
    }
}
fragment gateChecks on Commit {
    checkSuites(first: 10, filterBy: { checkName: $checkName }) {
        nodes { checkRuns(first: 20, filterBy: { checkName: $checkName }) { nodes { conclusion externalId completedAt } } }
    }
}`

function newest(timestamps) {
    const parsed = timestamps.map((t) => Date.parse(t)).filter(Number.isFinite)
    return parsed.length > 0 ? Math.max(...parsed) : null
}

function gateChecksOf(commit) {
    return (commit?.checkSuites?.nodes ?? []).flatMap((suite) => suite?.checkRuns?.nodes ?? [])
}

// The pull request as the GraphQL query returns it -> whether a full run counts as passed.
function fullRunState(pullRequest) {
    const heads = [
        ...(pullRequest.commits?.nodes ?? []).map((node) => node?.commit),
        ...(pullRequest.timelineItems?.nodes ?? []).map((node) => node?.beforeCommit),
    ]
    const lastFullPassAt = newest(
        heads
            .flatMap(gateChecksOf)
            .filter((check) => check?.conclusion === 'SUCCESS' && check.externalId === FULL_RUN_EXTERNAL_ID)
            .map((check) => check.completedAt)
    )
    const queueKickAt = newest(
        (pullRequest.comments?.nodes ?? [])
            .filter((comment) => TRUNK_LOGIN.test(comment?.author?.login ?? ''))
            .filter((comment) => QUEUE_FAILURE_WORDING.some((wording) => wording.test(comment.body ?? '')))
            .map((comment) => comment.updatedAt)
    )
    const rearmedByQueueKick = lastFullPassAt !== null && queueKickAt !== null && queueKickAt > lastFullPassAt
    return { passed: lastFullPassAt !== null && !rearmedByQueueKick, rearmedByQueueKick }
}

module.exports = { fullRunState, FULL_RUN_EXTERNAL_ID, GATE_CHECK_NAME }

if (require.main === module) {
    const [owner, name] = (process.env.GITHUB_REPOSITORY ?? '').split('/')
    const number = process.env.PR_NUMBER ?? ''
    if (!owner || !name || !/^[0-9]+$/.test(number)) {
        console.error('GITHUB_REPOSITORY and PR_NUMBER are required')
        process.exit(1)
    }
    const args = [
        'api',
        'graphql',
        '-F',
        `owner=${owner}`,
        '-F',
        `name=${name}`,
        '-F',
        `number=${number}`,
        '-f',
        `checkName=${GATE_CHECK_NAME}`,
        '-f',
        `query=${QUERY}`,
    ]
    const response = JSON.parse(execFileSync('gh', args, { encoding: 'utf-8', timeout: 60_000 }))
    const pullRequest = response.data?.repository?.pullRequest
    if (response.errors || !pullRequest) {
        console.error(`Could not read PR ${number}: ${JSON.stringify(response.errors ?? 'no pull request')}`)
        process.exit(1)
    }
    const { passed, rearmedByQueueKick } = fullRunState(pullRequest)
    console.error(`Full backend run already passed: ${passed}${rearmedByQueueKick ? ' (re-armed by a merge queue kick)' : ''}`)
    process.stdout.write(`passed=${passed}\nrearmed_by_queue_kick=${rearmedByQueueKick}\n`)
}
