import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { runScenario, withoutRandomIds, type ParityResult } from './run'
import { SCENARIOS } from './scenarios'

// Each golden is what posthog-cli sent to the fake server for the same files and flags
// (record-e2e.ts). hog must send the same requests, with the same bodies and uploaded bytes, and
// exit with the same code.
describe('hog error-tracking sends what posthog-cli sends', () => {
    test.each(SCENARIOS.map((scenario) => [scenario.name, scenario] as const))('%s', async (name, scenario) => {
        const golden = JSON.parse(
            readFileSync(join(import.meta.dir, 'golden', 'e2e', `${name}.json`), 'utf8')
        ) as ParityResult
        const result = await runScenario(scenario, 'hog')
        if (scenario.randomIds) {
            expect(withoutRandomIds(result)).toEqual(withoutRandomIds(golden))
        } else {
            expect(result).toEqual(golden)
        }
    })
})
