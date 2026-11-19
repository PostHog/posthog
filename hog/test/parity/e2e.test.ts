import { describe, expect, test } from 'bun:test'

import { contentHash, sourceAndMapPayload, SymbolDataType, writeSymbolData } from '@/error-tracking/container'

import { decodeFile, readGolden, runScenario, withoutRandomIds } from './run'
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

    test('process in symbol-set mode without a release uploads each bundle as it wrote it', async () => {
        const scenario = SCENARIOS.find(({ name }) => name === 'js-process-no-release')!

        const result = await runScenario(
            { ...scenario, hog: [...scenario.hog, '--release-mode', 'symbol-set'], fullSnapshot: true },
            'hog'
        )

        const files = result.files ?? {}
        const written = Object.keys(files)
            .filter((path) => files[`${path}.map`])
            .map((path) =>
                contentHash(
                    writeSymbolData(
                        SymbolDataType.SourceAndMap,
                        sourceAndMapPayload(decodeFile(files[path]!), decodeFile(files[`${path}.map`]!))
                    )
                )
            )
        const uploaded = result.requests.flatMap((request) => (request.upload ? [request.upload.sha512] : []))
        expect(written.length).toBeGreaterThan(1)
        expect(uploaded.sort()).toEqual(written.sort())
    })
})
