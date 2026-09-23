import { HogVMException } from '@posthog/hogvm'

import { compileHog } from '../templates/compiler'
import { HogFunctionFilterGlobals } from '../types'
import { runtimeContractHash } from './filter-runtime'
import { classifyHogError } from './hog-error-classification'
import { execHog } from './hog-exec'

// Every filter in this file is one we have seen fail in production, written fresh.
describe('classifyHogError', () => {
    const runtime = runtimeContractHash()
    const stale = 'contract-from-before-the-runtime-changed'

    const failingFilter = async (hog: string, globals: Partial<HogFunctionFilterGlobals> = {}): Promise<unknown> => {
        const bytecode = await compileHog(hog)
        const { error, execResult } = await execHog(bytecode, {
            globals: { event: '$pageview', properties: {}, ...globals },
        })
        const thrown = error ?? execResult?.error
        expect(thrown).toBeDefined()
        return thrown
    }

    describe('contract errors depend on what the filter was compiled against', () => {
        it.each([
            ['a query-only field', 'return $virt_is_bot = false'],
            [
                'a two-argument dateAdd, valid in HogQL and not in the VM',
                "return dateAdd(toIntervalDay(1), toDateTime('2026-01-01')) > now()",
            ],
        ])('%s', async (_name, hog) => {
            const error = await failingFilter(hog)
            // Saved before the compiler checked anything: the owner has to fix it, replay cannot.
            expect(classifyHogError(error, { bytecodeContract: undefined, runtimeContract: runtime })).toBe('legacy')
            // Compiled against an older runtime: we changed the contract, replay after the fix.
            expect(classifyHogError(error, { bytecodeContract: stale, runtimeContract: runtime })).toBe('drift')
            // Compiled against this runtime and still failing: the compiler and the VM disagree.
            expect(classifyHogError(error, { bytecodeContract: runtime, runtimeContract: runtime })).toBe('bug')
        })

        it('an aggregate that does not exist in Hog', async () => {
            const { error, execResult } = await execHog(['_H', 1, 33, 1, 2, 'countDistinctIf', 1], { globals: {} })
            expect(classifyHogError(error ?? execResult?.error, { runtimeContract: runtime })).toBe('legacy')
        })
    })

    describe('data errors are the same whatever the filter was compiled against', () => {
        it.each<[string, string, Partial<HogFunctionFilterGlobals>]>([
            ['a standard-library function refusing its argument', "return dateDiff('bogus', now(), now()) > 1", {}],
            [
                'a property of the wrong type for a standard-library function',
                "return length(splitByString(',', properties.tags)) > 1",
                { properties: { tags: 42 } },
            ],
            [
                'an invalid regex written into the filter',
                "return match(properties.url, '(')",
                { properties: { url: 'x' } },
            ],
            ["a throw in the filter's own code", "throw Error('boom')", {}],
        ])('%s', async (_name, hog, globals) => {
            const error = await failingFilter(hog, globals)
            for (const bytecodeContract of [undefined, stale, runtime]) {
                expect(classifyHogError(error, { bytecodeContract, runtimeContract: runtime })).toBe('data')
            }
        })
    })

    describe('platform errors are ours', () => {
        it('a resource limit', async () => {
            const bytecode = await compileHog('let i := 0; while (true) { i := i + 1 } return i')
            const { error, execResult } = await execHog(bytecode, { globals: {}, timeout: 1 })
            expect(classifyHogError(error ?? execResult?.error, { runtimeContract: runtime })).toBe('platform')
        })

        it('a JavaScript error the VM let through', () => {
            const error = new TypeError('Cannot convert undefined or null to object')
            expect(classifyHogError(error, { runtimeContract: runtime })).toBe('platform')
        })

        it('anything that is not an error object', () => {
            expect(classifyHogError('a string', { runtimeContract: runtime })).toBe('platform')
            expect(classifyHogError(undefined, { runtimeContract: runtime })).toBe('platform')
        })
    })

    it('follows the cause chain, so a wrapped input error keeps its class', () => {
        const wrapped = new Error('Could not execute bytecode for input field: url', {
            cause: new HogVMException('Global variable not found: distinct_id', 'contract'),
        })
        expect(classifyHogError(wrapped, { bytecodeContract: stale, runtimeContract: runtime })).toBe('drift')
    })
})
