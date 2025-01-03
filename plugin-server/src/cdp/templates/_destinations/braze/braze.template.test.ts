import { TemplateTester } from '../../test/test-helpers'
import { template } from './braze.template'

describe('braze template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const createInputs = (overrides = {}) => ({
        api_key: 'braze_api_key',
        instance: 'rest.iad-01.braze.com',
        external_id: 'user123',
        email: 'test@posthog.com',
        ...overrides,
    })

    const defaultEvent = {
        event: 'test_event',
        timestamp: '2024-01-01T12:00:00.000Z',
        properties: {
            foo: 'bar',
            test: true,
        },
    }

    it('should invoke the function successfully', async () => {
        const response = await tester.invoke(createInputs(), {
            event: defaultEvent,
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            Object {
              "body": "{\\"events\\":[{\\"name\\":\\"test_event\\",\\"time\\":\\"2024-01-01T12:00:00.000Z\\",\\"properties\\":{\\"foo\\":\\"bar\\",\\"test\\":true}}],\\"external_id\\":\\"user123\\",\\"email\\":\\"test@posthog.com\\"}",
              "headers": Object {
                "Authorization": "Bearer braze_api_key",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://rest.iad-01.braze.com/users/track",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ message: 'success' }),
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should require api key', async () => {
        const response = await tester.invoke(createInputs({ api_key: '' }))

        expect(response.finished).toBe(true)
        expect(response.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"No API key set. Skipping..."`
        )
    })

    it('should require either external_id or email', async () => {
        const response = await tester.invoke(createInputs({ external_id: '', email: '' }))

        expect(response.finished).toBe(true)
        expect(response.logs.filter((l) => l.level === 'info')[0].message).toMatchInlineSnapshot(
            `"No external_id or email set. Skipping..."`
        )
    })

    it('should handle errors', async () => {
        const response = await tester.invoke(createInputs())

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 400, headers: {} },
            body: JSON.stringify({ message: 'Invalid request' }),
        })

        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from Braze (status 400): {'message': 'Invalid request'}"`
        )
    })
})
