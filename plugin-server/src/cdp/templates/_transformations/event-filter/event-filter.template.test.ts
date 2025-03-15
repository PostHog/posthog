import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './event-filter.template'

describe('event-filter.template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should return the event unchanged', async () => {
        const testEvent = {
            event: 'test_event',
            properties: {
                $host: 'example.com',
                user_id: '12345',
                is_logged_in: true,
            },
            distinct_id: '123456',
        }
        
        mockGlobals = tester.createGlobals({
            event: testEvent,
        })

        const response = await tester.invoke({}, mockGlobals)

        expect(response.finished).toBe(true)
        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual(testEvent)
    })
}) 