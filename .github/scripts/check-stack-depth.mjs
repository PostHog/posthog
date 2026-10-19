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

// `stack.position` on the pull request counts merged layers, so count the open
// layers in the stacks API list instead, which runs from bottom to top.
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
        // Fails open so that a GitHub API outage cannot block every pull request. A failing
        // section from an earlier push is marked stale, because it no longer describes the head.
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
            `This pull request is layer ${depth} of its stack, counting open pull requests from the [bottom of the stack](https://github.com/${repo}/pull/${bottom.number}). CI allows ${maxOpenDepth} open layers.`,
            '',
            'Each layer starts its own CI runs on every push and restack, so every extra layer adds CI cost.',
            '',
            'To fix it, do one of these and then push:',
            '',
            '- Merge the lower layers first. Merged layers do not count.',
            '- Combine layers into fewer pull requests with `gh stack modify`.',
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
