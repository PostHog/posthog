import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './downsampling.template'

describe('downsampling.template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const run = async (inputs: Record<string, any>, globals: HogFunctionInvocationGlobals) => {
        const response = await tester.invoke(inputs, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return response.execResult
    }

    it('keeps every event at 100 percent', async () => {
        const globals = tester.createGlobals({ event: { distinct_id: 'user-1', properties: {} } })
        const result = await run({ percentage: 100 }, globals)
        expect(result).toBeTruthy()
    })

    it('drops every event at 0 percent', async () => {
        const globals = tester.createGlobals({ event: { distinct_id: 'user-1', properties: {} } })
        const result = await run({ percentage: 0 }, globals)
        expect(result).toBeFalsy()
    })

    it('is stable for a given distinct ID and monotonic as the percentage grows', async () => {
        const globals = tester.createGlobals({ event: { distinct_id: 'user-stable', properties: {} } })

        const keptAt = async (percentage: number): Promise<boolean> => Boolean(await run({ percentage }, globals))

        // Two runs at the same percentage agree (no randomness in stable mode).
        expect(await keptAt(50)).toBe(await keptAt(50))
        // Once kept at some percentage, still kept at a higher one.
        if (await keptAt(50)) {
            expect(await keptAt(90)).toBe(true)
        }
    })

    it('only samples the named triggering events', async () => {
        const globals = tester.createGlobals({
            event: { event: 'not_sampled', distinct_id: 'user-1', properties: {} },
        })
        // 0 percent would drop it, but it is not in the triggering list, so it is kept.
        const result = await run({ percentage: 0, triggeringEvents: 'only_this_one' }, globals)
        expect(result).toBeTruthy()
    })
})
