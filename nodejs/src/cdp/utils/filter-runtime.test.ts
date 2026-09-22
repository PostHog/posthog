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
                `${FILTER_GLOBALS_RELATIVE_PATH} is stale. Run: pnpm --filter=@posthog/nodejs run build:filter-globals\n` +
                    JSON.stringify({ expected, actual }, null, 2)
            )
        }
        expect(actual).toEqual(expected)
    })

    it('describes what a hog function is actually evaluated with', () => {
        const { roots, callables, functions, template_roots } = describeFilterRuntime()
        expect(roots).toEqual(expect.arrayContaining(['event', 'person', 'properties', 'group_0', '$group_4']))
        // In the type, but built only by the hogflow conditional-branch path, which does not compile
        // through compile_filters_bytecode. Listing it would let a destination save a filter that throws.
        expect(roots).not.toContain('cohort_ids')
        expect(callables).toEqual(expect.arrayContaining(['lower', 'toString']))
        // Resolvable but async, and the filter path runs with maxAsyncSteps 0.
        expect(callables).not.toContain('sleep')
        // Resolvable, but the closure it resolves to cannot be invoked. Calling arrayMap by name is
        // unaffected, because a call is not read as a global.
        expect(callables).not.toContain('arrayMap')
        expect(functions).toEqual(expect.objectContaining({ lower: [1, 1], arrayMap: [2, 2], sortableSemver: [1, 1] }))
        expect(functions).not.toHaveProperty('sleep')
        expect(callables).not.toContain('print')
        expect(functions).not.toHaveProperty('print')
        expect(template_roots).toEqual(expect.arrayContaining(['event', 'person', 'inputs', 'variables', 'request']))
        expect(template_roots).not.toContain('distinct_id')
        expect(template_roots).not.toContain('properties')
    })

    it('agrees with what the VM does when asked', async () => {
        // The tables say what resolves; this checks the tables mean what we think they mean. A filter
        // passes a name as a callback, so resolving it is only half of what has to work: the other half
        // is the VM invoking the closure it got back. Passing one through arrayMap covers both.
        const asCallback = async (name: string): Promise<string> => {
            const bytecode = ['_H', 1, 32, name, 1, 1, 32, 'A', 43, 1, 2, 'arrayMap', 2]
            const { error, execResult } = await execHog(bytecode, { globals: {} })
            return String(error ?? execResult?.error ?? '')
        }
        for (const name of ['lower', 'toString']) {
            expect(await asCallback(name)).toBe('')
        }
        expect(await asCallback('definitelyNotAGlobal')).toContain('Global variable not found')
        // The half a resolution-only check misses, and the reason arrayMap is not offered as one.
        expect(await asCallback('arrayMap')).toContain('Unsupported function call')

        // Every offered name has to survive both halves, or a filter that passes it saves and then
        // throws on every event. Other errors are the callback meeting one string argument, not the
        // contract breaking.
        const contractErrors = ['Global variable not found', 'Unsupported function call']
        const broken: string[] = []
        for (const name of describeFilterRuntime().callables) {
            const message = await asCallback(name)
            if (contractErrors.some((error) => message.includes(error))) {
                broken.push(`${name}: ${message}`)
            }
        }
        expect(broken).toEqual([])

        // Django checks a direct call against functions, so every name there has to run as one.
        const calledDirectly = async (name: string): Promise<string> => {
            const { error, execResult } = await execHog(['_H', 1, 2, name, 0], { globals: {} })
            return String(error ?? execResult?.error ?? '')
        }
        const notCallable: string[] = []
        for (const name of Object.keys(describeFilterRuntime().functions)) {
            const message = await calledDirectly(name)
            if (contractErrors.some((error) => message.includes(error))) {
                notCallable.push(`${name}: ${message}`)
            }
        }
        expect(notCallable).toEqual([])
        expect(await calledDirectly('definitelyNotAFunction')).toContain('Unsupported function call')
    })
})
