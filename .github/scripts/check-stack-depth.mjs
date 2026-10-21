#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

const MAX_OPEN_DEPTH = 5
export const EXEMPT_THROUGH_PR = 121285

export function checkStackDepth(pullRequests) {
    const open = pullRequests.filter((pr) => pr.state === 'open')
    const failed = open.slice(MAX_OPEN_DEPTH).some((pr) => !pr.number || pr.number > EXEMPT_THROUGH_PR)
    return {
        status: failed ? 'fail' : 'pass',
        depth: open.length,
        detail: failed
            ? `${open.length} open layers; the limit is ${MAX_OPEN_DEPTH}. Merge lower layers or split the stack using /stacking-prs before publishing.`
            : `${open.length} open layers; within the limit or exempt as an existing pull request.`,
    }
}

function checkLocalStack() {
    try {
        const { branches } = JSON.parse(
            execFileSync('gh', ['stack', 'view', '--json'], {
                encoding: 'utf-8',
                stdio: ['ignore', 'pipe', 'pipe'],
                timeout: 20_000,
            })
        )
        // On the trunk, gh stack view reports some stack with no current branch.
        const current = branches.findIndex((branch) => branch.isCurrent === true)
        if (current === -1 || branches.some((branch) => typeof branch?.isMerged !== 'boolean')) {
            throw new Error('Current branch is not in a recognized stack')
        }
        return checkStackDepth(
            branches
                .slice(0, current + 1)
                .map((branch) => ({ number: branch.pr?.number, state: branch.isMerged ? 'closed' : 'open' }))
        )
    } catch {
        return { status: 'skipped', detail: 'The current branch is not in a gh stack.' }
    }
}

async function checkPullRequest() {
    const { GITHUB_TOKEN, GITHUB_REPOSITORY, STACK_NUMBER } = process.env
    const prNumber = Number(process.env.PR_NUMBER)
    if (prNumber <= EXEMPT_THROUGH_PR) {
        return
    }
    try {
        const response = await fetch(`https://api.github.com/repos/${GITHUB_REPOSITORY}/stacks/${STACK_NUMBER}`, {
            headers: { Authorization: `Bearer ${GITHUB_TOKEN}`, Accept: 'application/vnd.github+json' },
            signal: AbortSignal.timeout(10_000),
        })
        if (!response.ok) {
            throw new Error(`GitHub API returned ${response.status}`)
        }
        const { pull_requests } = await response.json()
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
        await checkPullRequest()
    }
}
