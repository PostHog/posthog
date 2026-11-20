#!/usr/bin/env node

// Whether a full Backend CI run already passed on this pull request. turbo-discover then lets
// later pushes run the selected subset instead of the full matrices.
//
// A pass is the gate's Test results check, posted by GATE_APP_ID and concluded success with
// FULL_RUN_EXTERNAL_ID, on any head the pull request has had: its current commits, plus the heads
// that force-pushes replaced. Any other app can post a check with the same name and external id.
// The check lives on a commit, not on the branch, so a rebase or a master merge keeps it.
//
// A failed Trunk merge queue attempt after the newest pass re-arms full runs, until the next full
// run passes. Trunk's API reports only the pull request's current queue state and when it changed,
// so a pull request that was enqueued again since its failure no longer shows the failure. The
// merge queue still runs the full matrices, so a missed re-arm defers a failure to the queue.
//
// Input:  GH_TOKEN, TRUNK_API_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, BASE_REF
// Output: key=value lines for GITHUB_OUTPUT on stdout. A failed read exits non-zero and prints
//         nothing, which the workflow reads as "no full pass", so the run stays full.

const { execFileSync } = require('child_process')

const GATE_CHECK_NAME = 'Backend CI on Depot / Test results'
const GATE_APP_ID = 2492437
const FULL_RUN_EXTERNAL_ID = 'backend-matrix=full'
const TRUNK_API_URL = 'https://api.trunk.io/v1/getSubmittedPullRequest'
// Trunk's docs do not list the state values, so any state naming a failure counts.
const FAILED_QUEUE_STATE = /fail/i

const QUERY = `
query ($owner: String!, $name: String!, $number: Int!, $checkName: String!, $appId: Int!) {
    repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
            commits(last: 100) { nodes { commit { ...gateChecks } } }
            timelineItems(last: 100, itemTypes: [HEAD_REF_FORCE_PUSHED_EVENT]) {
                nodes { ... on HeadRefForcePushedEvent { beforeCommit { ...gateChecks } } }
            }
        }
    }
}
fragment gateChecks on Commit {
    checkSuites(first: 10, filterBy: { appId: $appId, checkName: $checkName }) {
        nodes {
            app { databaseId }
            checkRuns(first: 20, filterBy: { checkName: $checkName, checkType: ALL }) { nodes { conclusion externalId completedAt } }
        }
    }
}`

function newest(timestamps) {
    const parsed = timestamps.map((t) => (typeof t === 'number' ? t : Date.parse(t))).filter(Number.isFinite)
    return parsed.length > 0 ? Math.max(...parsed) : null
}

function headsOf(pullRequest) {
    return [
        ...(pullRequest.commits?.nodes ?? []).map((node) => node?.commit),
        ...(pullRequest.timelineItems?.nodes ?? []).map((node) => node?.beforeCommit),
    ]
}

// The query asks GitHub for GATE_APP_ID's suites only. An app token reads each suite's app as
// null, so a null app counts and only another app's id excludes a suite.
function gateChecksOf(commit) {
    return (commit?.checkSuites?.nodes ?? [])
        .filter((suite) => suite?.app === null || suite?.app?.databaseId === GATE_APP_ID)
        .flatMap((suite) => suite.checkRuns?.nodes ?? [])
}

// The pull request as the GraphQL query returns it, and its Trunk queue entry (null when it was
// never submitted) -> whether a full run counts as passed.
function fullRunState(pullRequest, queueEntry) {
    const lastFullPassAt = newest(
        headsOf(pullRequest)
            .flatMap(gateChecksOf)
            .filter((check) => check?.conclusion === 'SUCCESS' && check.externalId === FULL_RUN_EXTERNAL_ID)
            .map((check) => check.completedAt)
    )
    const queueFailedAt = FAILED_QUEUE_STATE.test(queueEntry?.state ?? '')
        ? newest([queueEntry.stateChangedAt ?? ''])
        : null
    const rearmedByQueueKick = lastFullPassAt !== null && queueFailedAt !== null && queueFailedAt > lastFullPassAt
    return { passed: lastFullPassAt !== null && !rearmedByQueueKick, rearmedByQueueKick }
}

module.exports = { fullRunState, FULL_RUN_EXTERNAL_ID, GATE_APP_ID, GATE_CHECK_NAME }

// -> the pull request's queue entry, or null when Trunk has none for it. Throws on any other answer.
async function readQueueEntry({ owner, name, number, baseRef, token }) {
    const response = await fetch(TRUNK_API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-api-token': token },
        body: JSON.stringify({
            repo: { host: 'github.com', owner, name },
            pr: { number: Number(number) },
            targetBranch: baseRef,
        }),
        signal: AbortSignal.timeout(30_000),
    })
    if (response.status === 404) {
        return null
    }
    if (!response.ok) {
        throw new Error(`Trunk answered ${response.status}`)
    }
    const entry = await response.json()
    return { state: entry.state, stateChangedAt: entry.stateChangedAt }
}

async function main() {
    const [owner, name] = (process.env.GITHUB_REPOSITORY ?? '').split('/')
    const number = process.env.PR_NUMBER ?? ''
    const trunkToken = process.env.TRUNK_API_TOKEN ?? ''
    if (!owner || !name || !/^[0-9]+$/.test(number) || !trunkToken) {
        console.error('GITHUB_REPOSITORY, PR_NUMBER and TRUNK_API_TOKEN are required')
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
        '-F',
        `appId=${GATE_APP_ID}`,
        '-f',
        `query=${QUERY}`,
    ]
    const response = JSON.parse(execFileSync('gh', args, { encoding: 'utf-8', timeout: 60_000 }))
    const pullRequest = response.data?.repository?.pullRequest
    if (response.errors || !pullRequest) {
        console.error(`Could not read PR ${number}: ${JSON.stringify(response.errors ?? 'no pull request')}`)
        process.exit(1)
    }
    let queueEntry
    try {
        queueEntry = await readQueueEntry({ owner, name, number, baseRef: process.env.BASE_REF || 'master', token: trunkToken })
    } catch (error) {
        console.error(`Could not read the merge queue state of PR ${number}: ${error.message}`)
        process.exit(1)
    }
    const heads = headsOf(pullRequest)
    const suites = heads.flatMap((commit) => commit?.checkSuites?.nodes ?? [])
    console.error(
        `Read: ${heads.length} heads, ${suites.length} gate check suites ` +
            `(app ids ${JSON.stringify([...new Set(suites.map((suite) => suite?.app?.databaseId ?? null))])}), ` +
            `${heads.flatMap(gateChecksOf).length} gate checks, ` +
            `queue state ${queueEntry ? `${queueEntry.state} since ${queueEntry.stateChangedAt}` : 'none'}`
    )
    const { passed, rearmedByQueueKick } = fullRunState(pullRequest, queueEntry)
    console.error(
        `Full backend run already passed: ${passed}${rearmedByQueueKick ? ' (re-armed by a failed merge queue attempt)' : ''}`
    )
    process.stdout.write(`passed=${passed}\nrearmed_by_queue_kick=${rearmedByQueueKick}\n`)
}

if (require.main === module) {
    main()
}
