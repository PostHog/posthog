import { TemplateTester } from '../../test/test-helpers'
import { template } from './flywheel.template'

describe('flywheel template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should send event to Flywheel', async () => {
        const response = await tester.invoke({
            apiKey: 'test-api-key',
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchObject({
            url: 'https://api.flywheel.cx/posthog/event-receiver',
            method: 'POST',
            headers: {
                Authorization: 'test-api-key',
                'Auth-Type': 'api',
                'Content-Type': 'application/json',
            },
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { success: true },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should throw on 4xx error', async () => {
        const response = await tester.invoke({
            apiKey: 'bad-key',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { error: 'Unauthorized' },
        })

        expect(fetchResponse.error).toContain('Failed to send event to Flywheel')
    })

    it('should throw on 5xx error', async () => {
        const response = await tester.invoke({
            apiKey: 'test-api-key',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 500,
            body: { error: 'Internal server error' },
        })

        expect(fetchResponse.error).toContain('Failed to send event to Flywheel')
    })
})
