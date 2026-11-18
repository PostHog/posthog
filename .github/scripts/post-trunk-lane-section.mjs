#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { gh, postSection, resolvePrContext } from '../../frontend/bin/ci-report/update-ci-report.mjs'

function formatTarget(target) {
    const escapedTarget = target.replace(
        /[&<>"']/g,
        (character) =>
            ({
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;',
            })[character]
    )
    return `<code>${escapedTarget}</code>`
}

export function buildTrunkLaneSection({ impactedTargets, isUniversal, crossLane = null }) {
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
    const laneName = runsBackendPythonTests ? 'backend Python lane' : 'non-backend lane'
    // A single target names the exact lane; more than one collapses to the
    // shared family name rather than listing them all.
    const summary = impactedTargets.length === 1 ? `${laneName} (${formatTarget(impactedTargets[0])})` : laneName

    const base = `This PR is assigned to the ${summary}. It ${runsBackendPythonTests ? 'runs' : 'does not run'} backend Python tests and may merge in parallel with PRs in other lanes.`
    if (crossLane?.mixed) {
        return {
            status: 'warn',
            summary: `${summary}, mixes lanes`,
            body: `${base}\n\n${crossLaneParagraph(crossLane)}`,
        }
    }
    return {
        status: runsBackendPythonTests ? 'warn' : 'ok',
        summary,
        body: base,
    }
}

// The telemetry caps each list, so the total arrives beside it.
function fileList(files, total = files.length) {
    const shown = files.slice(0, 3).map(formatTarget).join(', ')
    const count = Math.max(total, files.length)
    return count > 3 ? `${shown} and ${count - 3} more` : shown
}

function crossLaneParagraph({ heavyFiles, lightFiles, heavyCount, lightCount }) {
    return (
        `This PR changes Python or frontend code (${fileList(heavyFiles, heavyCount)}) and Node or Rust code (${fileList(lightFiles, lightCount)}) together. ` +
        'In the merge queue, every Node or Rust PR behind it in the same lane then runs the Django and frontend suites too, ' +
        'so the cross-lane check fails. Split it, or add the `cross-lane-change` label if the halves must land together.'
    )
}

// PR-controlled scripts produce these properties, so a wrong shape must not fail the section.
export function parseCrossLane(laneProperties) {
    const strings = (value) => (Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [])
    const heavyFiles = strings(laneProperties.cross_lane_heavy_files)
    const lightFiles = strings(laneProperties.cross_lane_light_files)
    if (laneProperties.cross_lane !== true || heavyFiles.length === 0 || lightFiles.length === 0) {
        return null
    }
    const count = (value, files) => (Number.isInteger(value) ? value : files.length)
    return {
        mixed: true,
        heavyFiles,
        lightFiles,
        heavyCount: count(laneProperties.cross_lane_heavy_file_count, heavyFiles),
        lightCount: count(laneProperties.cross_lane_light_file_count, lightFiles),
    }
}

export async function postTrunkLaneSection({
    impactedTargets,
    isUniversal,
    crossLane = null,
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

    const section = buildTrunkLaneSection({ impactedTargets, isUniversal, crossLane })
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
    const crossLane = parseCrossLane(laneProperties)

    await postTrunkLaneSection({
        impactedTargets,
        isUniversal,
        crossLane,
        expectedHeadSha: process.env.EXPECTED_HEAD_SHA,
        getCurrentHeadSha,
    })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
