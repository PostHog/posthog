import { readFileSync } from 'fs'
import { join } from 'path'

import { parseJSON } from '~/common/utils/json-parse'

import {
    FILTER_GLOBALS_RELATIVE_PATH,
    FilterRuntime,
    describeFilterRuntime,
    renderFilterGlobalsFile,
    runtimeContractHash,
} from './filter-runtime'
import { execHog } from './hog-exec'

describe('filter-runtime', () => {
    const committed = (): string => readFileSync(join(__dirname, '../../../..', FILTER_GLOBALS_RELATIVE_PATH), 'utf8')

    it('matches the committed file Django reads, byte for byte', () => {
        // The one gate. A global or a standard-library function added to the runtime lands here as a
        // diff until the file is regenerated, so Django cannot silently validate against a stale set.
        // Compared as text: the generator is the only writer of this file, and a reformat by hand or by
        // a tool would show up here as churn on every later regenerate.
        const expected = renderFilterGlobalsFile(describeFilterRuntime())
        const actual = committed()
        if (actual !== expected) {
            throw new Error(
                `${FILTER_GLOBALS_RELATIVE_PATH} differs from the generator's output. Run: pnpm --filter=@posthog/nodejs run build:filter-globals\n` +
                    JSON.stringify({ expected: parseJSON(expected), actual: parseJSON(actual) }, null, 2)
            )
        }
        expect(actual).toBe(expected)
    })

    it('hashes the contract, not the file', () => {
        // The hash is stamped on compiled bytecode and compared at run time, so it must move only when
        // what the runtime provides moves: never on whitespace, key order or the comment in the file.
        const runtime = describeFilterRuntime()
        const hash = runtimeContractHash(runtime)
        expect(hash).toMatch(/^[0-9a-f]{16}$/)
        expect(parseJSON(committed()).contract).toBe(hash)

        const reparsed = parseJSON(renderFilterGlobalsFile(runtime)) as FilterRuntime
        expect(runtimeContractHash(reparsed)).toBe(hash)

        const reordered: FilterRuntime = {
            ...runtime,
            functions: Object.fromEntries(Object.entries(runtime.functions).reverse()),
        }
        expect(runtimeContractHash(reordered)).toBe(hash)

        const narrowed: FilterRuntime = { ...runtime, functions: { ...runtime.functions, lower: [1, 0] } }
        expect(runtimeContractHash(narrowed)).not.toBe(hash)
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
