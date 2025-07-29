import { HogFunctionInvocationGlobals } from '~/cdp/types'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './default.template'

describe('default.template.ts', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = new Date('2024-01-01')
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())

        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    test_property: 'test_value',
                },
            },
        })
    })

    describe('transformation', () => {
        it('should execute successfully', async () => {
            const response = await tester.invoke({}, mockGlobals)
            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
        })

        it('should return the transformed event', async () => {
            const response = await tester.invoke({}, mockGlobals)
            expect(response.execResult).toEqual({
                distinct_id: 'distinct-id',
                elements_chain: '',
                event: 'event-name',
                properties: {
                    $example_added_property: 'example',
                    test_property: 'test_value',
                },
                timestamp: '2024-01-01T00:00:00Z',
                url: 'https://us.posthog.com/projects/1/events/1234',
                uuid: 'event-id',
            })
        })
    })
})
