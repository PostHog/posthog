import { describe, expect, test } from 'bun:test'

import { readGolden, runScenario, withoutRandomIds } from './run'
import { SCENARIOS } from './scenarios'

// Each golden is what posthog-cli sent to the fake server for the same files and flags
// (record-e2e.ts). hog must send the same requests, with the same bodies and uploaded bytes, write
// the same files, and exit with the same code.
describe('hog does what posthog-cli does', () => {
    test.each(SCENARIOS.map((scenario) => [scenario.name, scenario] as const))('%s', async (name, scenario) => {
        const golden = readGolden(name)
        const result = await runScenario(scenario, 'hog')
        if (scenario.randomIds) {
            expect(withoutRandomIds(result)).toEqual(withoutRandomIds(golden))
        } else {
            expect(result).toEqual(golden)
        }
    })
})
