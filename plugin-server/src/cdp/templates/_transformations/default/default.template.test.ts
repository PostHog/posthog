import { HogFunctionInvocationGlobals } from '../../../types'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './default.template'

describe('default template', () => {
    const tester = new TemplateTester(template)
    let mockGlobals: HogFunctionInvocationGlobals

    beforeEach(async () => {
        await tester.beforeEach()
        const date = new Date('2025-01-01')
        jest.useFakeTimers().setSystemTime(date)

        mockGlobals = tester.createGlobals({
            event: {
                properties: {
                    test_property: 'test_value',
                },
            },
        })
    })

    describe('transformation execution', () => {
        it('should execute successfully', async () => {
            const response = await tester.invoke({}, mockGlobals)

            expect(response.finished).toBe(true)
            expect(response.error).toBeUndefined()
        })

        it('should return correct logs', async () => {
            const response = await tester.invoke({}, mockGlobals)

            expect(response.logs).toMatchObject([
                {
                    level: 'debug',
                    message: expect.stringContaining('Executing function'),
                    timestamp: expect.any(Object),
                },
                {
                    level: 'debug',
                    message: expect.stringContaining(`Function completed. Event: ${mockGlobals.event.url}`),
                    timestamp: expect.any(Object),
                },
            ])
        })

        it('should have correct hogFunction configuration', async () => {
            const response = await tester.invoke({}, mockGlobals)

            expect(response.invocation.hogFunction).toMatchObject({
                status: 'alpha',
                type: 'transformation',
                id: 'template-blank-transformation',
                name: 'Custom transformation',
                description: 'This is a starter template for custom transformations',
                icon_url: '/static/hedgehog/builder-hog-01.png',
                category: ['Custom'],
                hog: `
// This is a blank template for custom transformations
// The function receives 'event' as a global object and expects it to be returned
// If you return null then the event will be discarded
return event
    `,
                inputs_schema: [],
                bytecode: ['_H', 1, 32, 'event', 1, 1, 38],
                inputs: {},
                team_id: 1,
                enabled: true,
            })
        })

        it('should preserve custom event properties', async () => {
            const response = await tester.invoke({}, mockGlobals)
            expect(response.invocation.globals.event.properties).toMatchObject({
                test_property: 'test_value',
            })
        })
    })
})
