#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import { pathToFileURL } from 'node:url'

import {
    clearSectionIfPresent,
    gh,
    postSection,
    resolvePrContext,
    updateSectionIfPresent,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'stack-depth'
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

async function main() {
    const context = resolvePrContext('stack depth check')
    if (!context) {
        return
    }
    const { token, repo, prNumber } = context
    if (prNumber <= EXEMPT_THROUGH_PR) {
        return
    }

    let result
    try {
        const stack = await gh(token, `/repos/${repo}/stacks/${process.env.STACK_NUMBER}`, {
            signal: AbortSignal.timeout(10_000),
        })
        const index = stack.pull_requests.findIndex((layer) => layer.number === prNumber)
        if (index === -1) {
            throw new Error(`Pull request ${prNumber} is absent from the stack response`)
        }
        result = checkStackDepth(stack.pull_requests.slice(0, index + 1))
    } catch (err) {
        process.exitCode = 1
        console.log(`::error title=Stack depth not checked::${err.message}. Retry this check.`)
        await updateSectionIfPresent({
            id: SECTION_ID,
            status: 'fail',
            summary: 'could not verify stack depth',
            body: 'The current stack could not be read from GitHub. Retry this check. The previous result no longer applies.',
        })
        return
    }

    if (result.status === 'pass') {
        await clearSectionIfPresent({
            id: SECTION_ID,
            summary: `within the limit of ${MAX_OPEN_DEPTH} open layers`,
            body: `This pull request is within the limit of ${MAX_OPEN_DEPTH} open stack layers.`,
        })
        return
    }

    await postSection({
        id: SECTION_ID,
        status: 'fail',
        summary: `open layer ${result.depth} of its stack, over the limit of ${MAX_OPEN_DEPTH}`,
        body: [
            result.detail,
            '',
            `[Stacking guide and recovery steps](https://github.com/${repo}/blob/master/.agents/skills/stacking-prs/SKILL.md#publish).`,
        ].join('\n'),
    })
    console.log(`::error title=Stack too deep::${result.detail}`)
    process.exitCode = 1
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    if (process.argv.includes('--local')) {
        const result = checkLocalStack()
        console.log(JSON.stringify(result))
        process.exitCode = result.status === 'fail' ? 1 : 0
    } else {
        await main()
    }
}
