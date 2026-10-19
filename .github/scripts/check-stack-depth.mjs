#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import {
    clearSectionIfPresent,
    gh,
    isReportComment,
    listPrComments,
    parseSections,
    postSection,
    resolvePrContext,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const MAX_OPEN_DEPTH = 5
const SECTION_ID = 'stack-depth'

// `stack.position` on the pull request counts merged layers, so count the open
// layers in the stacks API list instead, which runs from bottom to top.
export function openDepth(stack, prNumber) {
    const index = stack.pull_requests.findIndex((pr) => pr.number === prNumber)
    return stack.pull_requests.slice(0, index + 1).filter((pr) => pr.state === 'open').length
}

function buildOverDepthSection({ depth, bottomUrl }) {
    return {
        id: SECTION_ID,
        status: 'fail',
        summary: `layer ${depth} of its stack, the limit is ${MAX_OPEN_DEPTH}`,
        body: [
            `This pull request is layer ${depth} of its stack, counting open pull requests from the [bottom of the stack](${bottomUrl}). CI allows ${MAX_OPEN_DEPTH} open layers.`,
            '',
            'Each layer starts its own CI runs on every push and restack, so every extra layer adds CI cost.',
            '',
            'To fix it, do one of these and then push:',
            '',
            '- Merge the lower layers first. Merged layers do not count.',
            '- Combine layers into fewer pull requests with `gh stack modify`.',
        ].join('\n'),
    }
}

// Fails open so that a GitHub API outage cannot block every pull request. A failing
// section from an earlier push is marked stale, because it no longer describes the head.
async function markUnchecked(context, reason) {
    console.log(`::warning title=Stack depth not checked::${reason}`)
    const reportComment = (await listPrComments(context).catch(() => [])).find(isReportComment)
    if (!reportComment || !parseSections(reportComment.body).has(SECTION_ID)) {
        return
    }
    await postSection({
        id: SECTION_ID,
        status: 'info',
        summary: 'not checked on this push',
        body: 'The stack could not be read from the GitHub API, so the depth was not checked. The previous result no longer applies.',
    })
}

async function main() {
    const context = resolvePrContext('stack depth check')
    if (!context) {
        return
    }
    const { token, repo, prNumber } = context

    let stack
    try {
        const pr = await gh(token, `/repos/${repo}/pulls/${prNumber}`)
        stack = pr.stack ? await gh(token, `/repos/${repo}/stacks/${pr.stack.number}`) : null
    } catch (err) {
        await markUnchecked(context, err.message)
        return
    }

    const depth = stack ? openDepth(stack, prNumber) : 0
    if (depth <= MAX_OPEN_DEPTH) {
        await clearSectionIfPresent({
            id: SECTION_ID,
            summary: `within the limit of ${MAX_OPEN_DEPTH} open layers`,
            body: `This pull request is within the limit of ${MAX_OPEN_DEPTH} open stack layers.`,
        })
        return
    }

    const bottom = stack.pull_requests.find((pr) => pr.state === 'open')
    const section = buildOverDepthSection({ depth, bottomUrl: `https://github.com/${repo}/pull/${bottom.number}` })
    await postSection(section)
    console.log(
        `::error title=Stack too deep::This pull request is layer ${depth} of its stack. The limit is ${MAX_OPEN_DEPTH} open layers.`
    )
    process.exitCode = 1
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
