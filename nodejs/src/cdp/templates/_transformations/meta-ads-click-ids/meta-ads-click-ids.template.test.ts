import { TemplateTester } from '../../test/test-helpers'
import { template } from './meta-ads-click-ids.template'

interface EventResult {
    properties: {
        [key: string]: any
        $set_once?: {
            [key: string]: any
        }
    }
}

describe('meta-ads-click-ids.template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (properties: Record<string, any>, timestamp?: string): Promise<EventResult> => {
        const globals = tester.createGlobals({ event: { properties, ...(timestamp !== undefined && { timestamp }) } })
        const response = await tester.invoke({}, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return response.execResult as EventResult
    }

    it.each([
        ['a raw fbclid', 'AbC_123-x', 'fb.1.1704067200000.AbC_123-x'],
        ['an fbclid already in fbc form', 'fb.1.1700000000000.AbC_123-x', 'fb.1.1700000000000.AbC_123-x'],
        ['no fbclid', null, undefined],
    ])('derives the fbc value from %s', async (_, fbclid, expected) => {
        const result = await invoke({ fbclid })
        expect(result.properties.$set_once?.$meta_fbc).toEqual(expected)
    })

    it('generates an fbp value pinned to the event time', async () => {
        const result = await invoke({})
        expect(result.properties.$set_once?.$meta_fbp).toMatch(/^fb\.1\.1704067200000\.\d{10}$/)
    })

    it('falls back to the current time when the event has no timestamp', async () => {
        const result = await invoke({ fbclid: 'AbC_123-x' }, '')
        expect(result.properties.$set_once?.$meta_fbc).toMatch(/^fb\.1\.\d{13}\.AbC_123-x$/)
    })
})
