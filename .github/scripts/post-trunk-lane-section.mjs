#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { gh, postSection, resolvePrContext } from '../../frontend/bin/ci-report/update-ci-report.mjs'

export function buildTrunkLaneSection({ impactedTargets, isUniversal }) {
    if (
        isUniversal ||
        !Array.isArray(impactedTargets) ||
        !impactedTargets.every((target) => typeof target === 'string')
    ) {
        return {
            status: 'alert',
            summary: 'universal lane',
            body: 'This PR is assigned to the universal lane. It cannot merge in parallel with other PRs, so it can take longer to merge. Ask dev-ex if you think this is wrong.',
        }
    }

    const runsBackendPythonTests = impactedTargets.some((target) => target.startsWith('py:'))
    const summary = runsBackendPythonTests ? 'backend Python lane' : 'non-backend lane'

    return {
        status: runsBackendPythonTests ? 'warn' : 'ok',
        summary,
        body: `This PR is assigned to the ${summary}. It ${runsBackendPythonTests ? 'runs' : 'does not run'} backend Python tests and may merge in parallel with PRs in other lanes.`,
    }
}

export async function postTrunkLaneSection({
    impactedTargets,
    isUniversal,
    expectedHeadSha,
    getCurrentHeadSha,
    post = postSection,
}) {
    let currentHeadSha
    try {
        currentHeadSha = await getCurrentHeadSha()
    } catch (error) {
        console.warn(`Could not verify the current PR head: ${error.message}`)
        return false
    }

    if (!expectedHeadSha || currentHeadSha !== expectedHeadSha) {
        console.info(`Skipping stale Trunk lane assignment for ${expectedHeadSha || 'an unknown commit'}.`)
        return false
    }

    const section = buildTrunkLaneSection({ impactedTargets, isUniversal })
    await post({ id: 'trunk-lane', ...section })
    return true
}

function parseJson(value) {
    try {
        const parsed = JSON.parse(value || '{}')
        return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
        return {}
    }
}

async function getCurrentHeadSha() {
    const context = resolvePrContext('checking the current PR head')
    if (!context) {
        return null
    }
    const pullRequest = await gh(context.token, `/repos/${context.repo}/pulls/${context.prNumber}`)
    return pullRequest.head?.sha ?? null
}

async function main() {
    const impactedTargets = parseJson(process.env.IMPACTED_TARGETS).impactedTargets
    const laneProperties = parseJson(process.env.LANE_PROPERTIES)
    const isUniversal = typeof laneProperties.is_all === 'boolean' ? laneProperties.is_all : true

    await postTrunkLaneSection({
        impactedTargets,
        isUniversal,
        expectedHeadSha: process.env.EXPECTED_HEAD_SHA,
        getCurrentHeadSha,
    })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
