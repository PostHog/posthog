import { TemplateTester } from '../../test/test-helpers'
import { template } from './avo.template'

describe('avo template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    const createInputs = (overrides = {}) => ({
        api_key: 'avo_api_key',
        environment: 'production',
        ...overrides,
    })

    const defaultEvent = {
        event: 'test_event',
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
              "body": "{\\"apiKey\\":\\"avo_api_key\\",\\"env\\":\\"production\\",\\"eventName\\":\\"test_event\\",\\"eventProperties\\":{\\"foo\\":\\"bar\\",\\"test\\":true},\\"systemProperties\\":{\\"source\\":\\"posthog\\",\\"sourceVersion\\":\\"1.0.0\\"}}",
              "headers": Object {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://api.avo.app/track",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: JSON.stringify({ ok: true }),
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

    it('should handle errors', async () => {
        const response = await tester.invoke(createInputs())

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 400, headers: {} },
            body: JSON.stringify({ error: 'Invalid API key' }),
        })

        expect(fetchResponse.error).toMatchInlineSnapshot(`"Error from Avo (status 400): {'error': 'Invalid API key'}"`)
    })
})
