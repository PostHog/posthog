import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './drop-events.template'

describe('drop-events.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should drop events', async () => {
        mockGlobals = tester.createGlobals({
            event: {
                event: 'test_event',
                properties: {
                    key1: 'value1',
                    key2: 'value2',
                },
            },
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toBeNull()
    })
})
