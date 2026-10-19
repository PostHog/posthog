#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import {
    clearSectionIfPresent,
    gh,
    postSection,
    resolvePrContext,
    updateSectionIfPresent,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'stack-depth'

// `stack.position` counts merged layers, so count the open ones from the bottom.
export function openDepth(stack, prNumber) {
    const index = stack.pull_requests.findIndex((pr) => pr.number === prNumber)
    return stack.pull_requests.slice(0, index + 1).filter((pr) => pr.state === 'open').length
}

async function main() {
    const context = resolvePrContext('stack depth check')
    if (!context) {
        return
    }
    const { token, repo, prNumber } = context
    const maxOpenDepth = Number(process.env.MAX_OPEN_DEPTH)

    let stack
    try {
        stack = await gh(token, `/repos/${repo}/stacks/${process.env.STACK_NUMBER}`)
    } catch (err) {
        // Fail open, so an API outage can't block every pull request.
        console.log(`::warning title=Stack depth not checked::${err.message}`)
        await updateSectionIfPresent({
            id: SECTION_ID,
            status: 'info',
            summary: 'not checked on this push',
            body: 'The stack could not be read from the GitHub API, so the depth was not checked. The previous result no longer applies.',
        })
        return
    }

    const depth = openDepth(stack, prNumber)
    if (depth <= maxOpenDepth) {
        await clearSectionIfPresent({
            id: SECTION_ID,
            summary: `within the limit of ${maxOpenDepth} open layers`,
            body: `This pull request is within the limit of ${maxOpenDepth} open stack layers.`,
        })
        return
    }

    const bottom = stack.pull_requests.find((pr) => pr.state === 'open')
    await postSection({
        id: SECTION_ID,
        status: 'fail',
        summary: `layer ${depth} of its stack, the limit is ${maxOpenDepth}`,
        body: [
            `This pull request is layer ${depth} of its stack, counting open pull requests from the [bottom](https://github.com/${repo}/pull/${bottom.number}). The limit is ${maxOpenDepth}, because every layer reruns CI on each push and restack.`,
            '',
            'To fix it, merge the lower layers, or move this layer and the ones above it into a new stack on top with `gh stack init --base <branch>`. The new stack rebases onto `master` once the lower one merges.',
        ].join('\n'),
    })
    console.log(
        `::error title=Stack too deep::This pull request is layer ${depth} of its stack. The limit is ${maxOpenDepth} open layers.`
    )
    process.exitCode = 1
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
