import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './drop-events.template'

describe('drop-events.template', () => {
    const testTemplate = {
        ...template,
        filters: {
            events: [
                {
                    id: '1111',
                    name: 'All events',
                    type: 'events' as const,
                    order: 0,
                },
            ],
            actions: [],
            bytecode: ['_H', 1, 29, 3, 0, 4, 2],
        },
    }

    const tester = new TemplateTester(testTemplate)
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
        expect(response.execResult).toBeUndefined()
    })
})
