#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

export function buildTrunkLaneSection({ impactedTargets, isUniversal }) {
    if (
        isUniversal ||
        !Array.isArray(impactedTargets) ||
        !impactedTargets.every((target) => typeof target === 'string')
    ) {
        return {
            status: 'fail',
            summary: 'universal lane',
            body: 'This PR is assigned to the universal lane. Trunk will merge it on its own.',
        }
    }

    if (impactedTargets.some((target) => target.startsWith('py:'))) {
        return {
            status: 'warn',
            summary: 'runs backend Python tests',
            body: 'This PR is assigned to a lane that runs backend Python tests.',
        }
    }

    return {
        status: 'ok',
        summary: 'does not run backend Python tests',
        body: 'This PR is assigned to a lane that does not run backend Python tests.',
    }
}

function parseJson(value) {
    try {
        const parsed = JSON.parse(value || '{}')
        return parsed && typeof parsed === 'object' ? parsed : {}
    } catch {
        return {}
    }
}

async function main() {
    const impactedTargets = parseJson(process.env.IMPACTED_TARGETS).impactedTargets
    const laneProperties = parseJson(process.env.LANE_PROPERTIES)
    const isUniversal = typeof laneProperties.is_all === 'boolean' ? laneProperties.is_all : true
    const section = buildTrunkLaneSection({ impactedTargets, isUniversal })

    await postSection({ id: 'trunk-lane', ...section })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
