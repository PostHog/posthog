import { readFileSync } from 'fs'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import { FILTER_GLOBALS_RELATIVE_PATH, describeFilterRuntime, renderFilterGlobalsFile } from './filter-runtime'
import { execHog } from './hog-exec'

describe('filter-runtime', () => {
    const committed = (): string => readFileSync(join(__dirname, '../../../..', FILTER_GLOBALS_RELATIVE_PATH), 'utf8')

    it('matches the committed file Django reads', () => {
        // The one gate. A global or a standard-library function added to the runtime lands here as a
        // diff until the file is regenerated, so Django cannot silently validate against a stale set.
        // Compared as parsed JSON: the pre-commit hook reformats the file, and whitespace is not the
        // contract.
        const expected = parseJSON(renderFilterGlobalsFile(describeFilterRuntime()))
        const actual = parseJSON(committed())
        if (JSON.stringify(actual) !== JSON.stringify(expected)) {
            // toEqual alone prints a diff and nothing else; say what to do about it.
            throw new Error(
                `${FILTER_GLOBALS_RELATIVE_PATH} is stale. Run: pnpm --filter=@posthog/plugin-server run build:filter-globals\n` +
                    JSON.stringify({ expected, actual }, null, 2)
            )
        }
        expect(actual).toEqual(expected)
    })

    it('describes what a hog function is actually evaluated with', () => {
        const { roots, callables } = describeFilterRuntime()
        expect(roots).toEqual(expect.arrayContaining(['event', 'person', 'properties', 'group_0', '$group_4']))
        // In the type, but built only by the hogflow conditional-branch path, which does not compile
        // through compile_filters_bytecode. Listing it would let a destination save a filter that throws.
        expect(roots).not.toContain('cohort_ids')
        expect(callables).toEqual(expect.arrayContaining(['lower', 'arrayMap', 'toString']))
        // Resolvable but async, and the filter path runs with maxAsyncSteps 0.
        expect(callables).not.toContain('sleep')
    })

    it('agrees with what the VM does when asked', async () => {
        // The tables say what resolves; this checks the tables mean what we think they mean.
        const resolves = async (name: string): Promise<boolean> => {
            const { error, execResult } = await execHog(['_H', 1, 32, name, 1, 1], { globals: {} })
            return !String(error ?? execResult?.error ?? '').includes('Global variable not found')
        }
        for (const name of ['lower', 'arrayMap', 'toString']) {
            expect(await resolves(name)).toBe(true)
        }
        expect(await resolves('definitelyNotAGlobal')).toBe(false)
    })
})
