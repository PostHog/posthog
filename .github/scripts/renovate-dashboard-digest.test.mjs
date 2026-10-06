import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { parseDashboard } from './renovate-dashboard-digest.mjs'

const DASHBOARD = `This issue lists Renovate updates and detected dependencies.

## Config Migration Needed

 - [ ] <!-- create-config-migration-pr --> Select this checkbox to let Renovate create an automated Config Migration PR.

## Deprecations / Replacements
> [!WARNING]
The following dependencies are either deprecated or have replacements available.

| Datasource | Package | Replacement PR? |
|------------|------|--------------|
| npm | \`left-pad\` | ![Unavailable](https://img.shields.io/badge/unavailable-orange?style=flat-square) |
| npm | [old-lib](https://example.com/old-lib) | ![Available](https://img.shields.io/badge/available-green?style=flat-square) |

## Pending Approval

The following branches are pending approval. To create them, click on a checkbox below.

 - [ ] <!-- approve-branch=renovate/widget-5.x -->chore(deps): update dependency widget to v5
 - [ ] <!-- approve-branch=renovate/gadget-2.x-lockfile -->chore(deps): update dependency gadget to v2.4.1
 - [ ] <!-- approve-branch=renovate/sprocket-1.x -->fix(deps): update dependency sprocket to ^1.9.0
 - [ ] <!-- approve-all-pending-prs -->🔐 **Create all pending approval PRs at once** 🔐

## Errored

 - [ ] <!-- retry-branch=renovate/cog-3.x -->chore(deps): update dependency cog to v3

## Open

 - [ ] <!-- rebase-branch=renovate/gear-4.x -->[chore(deps): update dependency gear to v4](../pull/1)

## Vulnerabilities

> ❗ **Important**
>
> \`3\`/\`7\` CVEs have possible Renovate fixes.

## Detected Dependencies
`

describe('renovate dashboard digest', () => {
    it('summarizes a complete dashboard', () => {
        assert.deepEqual(parseDashboard(DASHBOARD), {
            pending: 3,
            pendingMajor: 1,
            open: 1,
            errored: 1,
            deprecated: 2,
            cves: { fixable: 3, total: 7 },
            configMigrationNeeded: true,
            truncated: false,
        })
    })

    it('flags a dashboard cut off at the issue size limit', () => {
        const cutOff = `${DASHBOARD.slice(0, DASHBOARD.indexOf('## Errored'))}\n> ✂ PR body was truncated to here.\n`
        const summary = parseDashboard(cutOff)
        assert.equal(summary.truncated, true)
        assert.equal(summary.cves, null)
        assert.equal(summary.pending, 3)
    })
})
