import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { summarize } from './renovate-dashboard-digest.mjs'

const update = (branchName, updateType) => ({ branchName, updateType })

const REPORT = {
    repositories: {
        local: {
            packageFiles: {
                npm: [
                    {
                        packageFile: 'package.json',
                        deps: [
                            { depName: 'widget', updates: [update('renovate/widget-5.x', 'major')] },
                            {
                                depName: 'gadget',
                                deprecationMessage: 'use gizmo',
                                updates: [update('renovate/gadget-2.x', 'minor'), update('renovate/gadget-3.x', 'major')],
                            },
                            { depName: 'pinned', updates: [] },
                        ],
                    },
                    {
                        packageFile: 'apps/web/package.json',
                        deps: [
                            { depName: 'react', updates: [update('renovate/react-monorepo', 'patch')] },
                            { depName: 'react-dom', updates: [update('renovate/react-monorepo', 'minor')] },
                            { depName: 'widget', updates: [update('renovate/widget-5.x', 'major')] },
                        ],
                    },
                ],
                'github-actions': [
                    {
                        packageFile: '.github/workflows/build.yml',
                        deps: [
                            { depName: 'acme/setup', warnings: [{ message: 'Could not determine new digest' }] },
                            { depName: 'acme/deploy', updates: [update('renovate/github-actions', 'digest')] },
                        ],
                    },
                ],
            },
        },
    },
}

describe('renovate dashboard digest', () => {
    it('counts each branch once, under its riskiest update type', () => {
        assert.deepEqual(summarize(REPORT), {
            pending: {
                npm: { major: 2, minor: 2, patch: 0, other: 0, total: 4 },
                'github-actions': { major: 0, minor: 0, patch: 0, other: 1, total: 1 },
            },
            deprecated: 1,
            lookupWarnings: 1,
        })
    })
})
