import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

import { createApiToolLibrary } from '@posthog/mcp/dist/cli-library.mjs'
import { loadStack } from '@posthog/sdk/stack'

// This repository's own stacks, in .ph/. Each folder's description.json is what the
// engine is compared against, so a change to a definition has to change it too.
const repository = fileURLToPath(new URL('../../..', import.meta.url))
const { stacks } = JSON.parse(readFileSync(join(repository, 'posthog.json'), 'utf8'))
const validator = createApiToolLibrary()

for (const [name, { dir }] of Object.entries(stacks)) {
    // A ported tile keeps its original's grid fields, which PostHog drops, so each one warns.
    test(`the ${name} stack evaluates to its description.json, with no problems beyond dropped layout fields`, async () => {
        const result = await loadStack(join(repository, dir), { root: repository, validator })
        assert.deepEqual(
            result.problems.filter(
                (problem) => problem.code !== 'layout_field_dropped' || problem.severity !== 'warning'
            ),
            []
        )
        const committed = JSON.parse(readFileSync(join(repository, dir, 'description.json'), 'utf8'))
        assert.deepEqual(result.description, committed)
    })
}
