import { TemplateTester } from '../../test/test-helpers'
import { template } from './pubsub.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    auth: { access_token: 'ACCESS_TOKEN' },
    topicId: 'projects/posthog/topics/events',
    payload: { event: 'event-name' },
    attributes: { source: 'posthog' },
    ...overrides,
})
describe('google pubsub template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('publishes the message', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"messages":[{"messageId":"event-id","data":"eyJldmVudCI6ImV2ZW50LW5hbWUifQ==","attributes":{"source":"posthog"}}]}",
              "headers": {
                "Authorization": "Bearer ACCESS_TOKEN",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://pubsub.googleapis.com/v1/projects/posthog/topics/events:publish",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { messageIds: ['1'] },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'Event sent successfully!'
        )
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 404,
            body: { error: 'topic not found' },
        })
        expect(result.error).toMatchInlineSnapshot(
            `"Error from pubsub.googleapis.com (status 404): {'error': 'topic not found'}"`
        )
    })
})
