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
function openDepth(stack, prNumber) {
    const index = stack.pull_requests.findIndex((pr) => pr.number === prNumber)
    return stack.pull_requests.slice(0, index + 1).filter((pr) => pr.state === 'open').length
}

// A stack can start on the branch of another open pull request, and that pull request
// runs CI too. The count follows each base branch down to the default branch, so a
// deep stack split into two stacks gets the same count as the single stack.
export async function chainedOpenDepth({ stack, prNumber, defaultBranch, findOpenPrByHead, getStack }) {
    let depth = openDepth(stack, prNumber)
    let baseRef = stack.base.ref
    const visited = new Set()
    while (baseRef !== defaultBranch && !visited.has(baseRef)) {
        visited.add(baseRef)
        const pr = await findOpenPrByHead(baseRef)
        if (!pr) {
            break
        }
        if (pr.stack) {
            const lowerStack = await getStack(pr.stack.number)
            depth += openDepth(lowerStack, pr.number)
            baseRef = lowerStack.base.ref
        } else {
            depth += 1
            baseRef = pr.base.ref
        }
    }
    return depth
}

async function main() {
    const context = resolvePrContext('stack depth check')
    if (!context) {
        return
    }
    const { token, repo, prNumber } = context
    const maxOpenDepth = Number(process.env.MAX_OPEN_DEPTH)
    const defaultBranch = process.env.DEFAULT_BRANCH
    const owner = repo.split('/')[0]

    let depth
    try {
        const getStack = (number) => gh(token, `/repos/${repo}/stacks/${number}`)
        depth = await chainedOpenDepth({
            stack: await getStack(process.env.STACK_NUMBER),
            prNumber,
            defaultBranch,
            findOpenPrByHead: async (ref) =>
                (await gh(token, `/repos/${repo}/pulls?state=open&head=${owner}:${encodeURIComponent(ref)}`))[0],
            getStack,
        })
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

    if (depth <= maxOpenDepth) {
        await clearSectionIfPresent({
            id: SECTION_ID,
            summary: `within the limit of ${maxOpenDepth} open layers`,
            body: `This pull request is within the limit of ${maxOpenDepth} open stack layers.`,
        })
        return
    }

    await postSection({
        id: SECTION_ID,
        status: 'fail',
        summary: `${depth} open layers, the limit is ${maxOpenDepth}`,
        body: [
            `This pull request has ${depth} open pull requests at or below it, down to \`${defaultBranch}\`. The layers of any stack this one starts from count too. CI allows ${maxOpenDepth}.`,
            '',
            'Each open pull request runs CI on every push and restack, so each extra layer adds CI cost.',
            '',
            'To fix it, do one of these:',
            '',
            '- Merge the lower layers. Merged pull requests do not count. The check runs again on the next push.',
            '- Close this pull request and the ones above it. Reopen them after the lower layers merge.',
            '',
            'To keep working on top of this stack, start a new stack from its top branch with `gh stack init --base <top branch>`. Push it with `gh stack push`, which opens no pull requests. Open its pull requests after this stack merges, because an open stack on top counts toward the limit.',
        ].join('\n'),
    })
    console.log(
        `::error title=Stack too deep::This pull request has ${depth} open pull requests at or below it. The limit is ${maxOpenDepth}.`
    )
    process.exitCode = 1
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
