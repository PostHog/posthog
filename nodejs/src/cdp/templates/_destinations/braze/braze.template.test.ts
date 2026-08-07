import { TemplateTester } from '../../test/test-helpers'
import { template } from './braze.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    brazeEndpoint: 'https://rest.fra-01.braze.eu',
    apiKey: 'my_secret_key',
    attributes: { email: '{person.properties.email}' },
    event: {
        name: '{event.event}',
        time: '{event.timestamp}',
        properties: '{event.properties}',
        external_id: '{event.distinct_id}',
    },
    ...overrides,
})
describe('braze template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('tracks the user', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(
            `
            {
              "body": "{"attributes":[{"email":"example@posthog.com"}],"events":[{"name":"event-name","time":"2024-01-01T00:00:00Z","properties":{"$current_url":"https://example.com"},"external_id":"distinct-id"}]}",
              "headers": {
                "Authorization": "Bearer my_secret_key",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://rest.fra-01.braze.eu/users/track",
            }
        `
        )
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: { message: 'success' },
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
            status: 401,
            body: { message: 'invalid api key' },
        })
        expect(result.error).toMatchInlineSnapshot(`"Error sending event: 401 {'message': 'invalid api key'}"`)
    })
})
