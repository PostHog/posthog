import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './timestamp-parser.template'

describe('timestamp-parser.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const invoke = async (globals: HogFunctionInvocationGlobals): Promise<any> => {
        const response = await tester.invoke({}, globals)
        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        return response.execResult as any
    }

    it('parses an ISO timestamp into date parts', async () => {
        mockGlobals = tester.createGlobals({
            event: { timestamp: '2024-01-01T13:37:00Z', properties: {} },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties.day_of_the_week).toBe('Monday')
        expect(result.properties.day).toBe(1)
        expect(result.properties.month).toBe(1)
        expect(result.properties.year).toBe(2024)
        expect(result.properties.hour).toBe(13)
        expect(result.properties.minute).toBe(37)
    })

    it('parses a numeric unix timestamp in seconds', async () => {
        // 2024-01-01T13:37:00Z as unix seconds. Cast because the globals type declares a string
        // timestamp, but SDKs can send a numeric one, which this template handles.
        mockGlobals = tester.createGlobals({
            event: { timestamp: 1704116220 as unknown as string, properties: {} },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties.year).toBe(2024)
        expect(result.properties.hour).toBe(13)
        expect(result.properties.minute).toBe(37)
    })

    it('writes no date properties for an unparseable timestamp', async () => {
        mockGlobals = tester.createGlobals({
            event: { timestamp: 'not a real timestamp', properties: { keep: 'me' } },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties.year).toBeUndefined()
        expect(result.properties.day_of_the_week).toBeUndefined()
        expect(result.properties.keep).toBe('me')
    })

    it('leaves the event unchanged when there is no timestamp', async () => {
        mockGlobals = tester.createGlobals({
            event: { timestamp: '', properties: { keep: 'me' } },
        })

        const result = await invoke(mockGlobals)

        expect(result.properties).toEqual({ keep: 'me' })
    })
})
