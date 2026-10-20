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
        console.log(`::warning title=Stack depth not checked::${err.message}`)
        await updateSectionIfPresent({
            id: SECTION_ID,
            status: 'info',
            summary: 'not checked on the latest run',
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

    const openLayers = stack.pull_requests.filter((pr) => pr.state === 'open')
    const pullUrl = (pr) => `https://github.com/${repo}/pull/${pr.number}`
    await postSection({
        id: SECTION_ID,
        status: 'fail',
        summary: `open layer ${depth} of its stack, over the limit of ${maxOpenDepth}`,
        body: [
            `This pull request is open layer ${depth} of its stack, counting from the [bottom](${pullUrl(openLayers[0])}). The limit is ${maxOpenDepth}, because each restack force-pushes every layer and reruns CI on all of them.`,
            '',
            'To fix it, merge the lower layers, or split the stack:',
            '',
            '1. Drop this layer and the ones above it from the stack with `gh stack modify`. Their pull requests stay open.',
            `2. Check out one of the dropped branches. Stack them on the branch of [open layer ${maxOpenDepth}](${pullUrl(openLayers[maxOpenDepth - 1])}) with \`gh stack init --base <that branch> <their branches>\`, then run \`gh stack submit\`.`,
            '3. Once the lower stack merges, rebase the new stack onto `master`.',
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
