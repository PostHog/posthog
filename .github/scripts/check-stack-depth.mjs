#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

const MAX_OPEN_DEPTH = 5
export const EXEMPT_THROUGH_PR = 121285
const SKIPPED = { status: 'skipped', detail: 'The current branch is not in a gh stack.' }

export function checkStackDepth(pullRequests) {
    const open = pullRequests.filter((pr) => pr.state === 'open')
    const failed = open.slice(MAX_OPEN_DEPTH).some((pr) => !pr.number || pr.number > EXEMPT_THROUGH_PR)
    return failed
        ? {
              status: 'fail',
              detail: `${open.length} open layers; the limit is ${MAX_OPEN_DEPTH}. Merge lower layers or split the stack using /stacking-prs before publishing.`,
          }
        : {
              status: 'pass',
              detail: `${open.length} open layers; within the limit or exempt as an existing pull request.`,
          }
}

function gh(args) {
    return JSON.parse(
        execFileSync('gh', args, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 20_000 })
    )
}

function checkLocalStack() {
    let branches
    try {
        ;({ branches } = gh(['stack', 'view', '--json']))
    } catch {
        return SKIPPED
    }
    // On the trunk, gh stack view reports some stack with no current branch.
    if (!branches?.some((branch) => branch.isCurrent === true)) {
        return SKIPPED
    }
    // gh stack submit and push publish every layer, whichever branch is checked out.
    return checkStackDepth(
        branches.map((branch) => ({
            number: branch.pr?.number,
            state: branch.isMerged || branch.pr?.state === 'CLOSED' ? 'closed' : 'open',
        }))
    )
}

function checkPullRequest() {
    const prNumber = Number(process.env.PR_NUMBER)
    if (prNumber <= EXEMPT_THROUGH_PR) {
        return
    }
    try {
        const { pull_requests } = gh([
            'api',
            `repos/${process.env.GITHUB_REPOSITORY}/stacks/${process.env.STACK_NUMBER}`,
        ])
        const index = pull_requests.findIndex((layer) => layer.number === prNumber)
        if (index === -1) {
            throw new Error(`Pull request ${prNumber} is absent from the stack response`)
        }
        const result = checkStackDepth(pull_requests.slice(0, index + 1))
        if (result.status === 'fail') {
            console.log(`::error title=Stack too deep::${result.detail}`)
            process.exitCode = 1
        }
    } catch (err) {
        console.log(`::error title=Stack depth not checked::${err.message}. Retry this check.`)
        process.exitCode = 1
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    if (process.argv.includes('--local')) {
        const result = checkLocalStack()
        console.log(JSON.stringify(result))
        process.exitCode = result.status === 'fail' ? 1 : 0
    } else {
        checkPullRequest()
    }
}
