import { TemplateTester } from '../test/test-helpers'
import { template } from './webhook.template'

describe('webhook template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(new Date('2025-01-01'))
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke({
            url: 'https://example.com?v={event.properties.$lib_version}',
            debug: false,
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            Object {
              "body": "{\\"value\\":{\\"event\\":{\\"uuid\\":\\"event-id\\",\\"event\\":\\"event-name\\",\\"distinct_id\\":\\"distinct-id\\",\\"properties\\":{\\"$current_url\\":\\"https://example.com\\"},\\"timestamp\\":\\"2024-01-01T00:00:00Z\\",\\"elements_chain\\":\\"\\",\\"url\\":\\"https://us.posthog.com/projects/1/events/1234\\"},\\"person\\":{\\"id\\":\\"person-id\\",\\"name\\":\\"person-name\\",\\"properties\\":{\\"email\\":\\"example@posthog.com\\"},\\"url\\":\\"https://us.posthog.com/projects/1/persons/1234\\"}}}",
              "headers": Object {
                "value": Object {
                  "Content-Type": "application/json",
                },
              },
              "method": Object {
                "value": "POST",
              },
              "return_queue": "hog",
              "url": "https://example.com?v=",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: '{"message": "Hello, world!"}',
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should log details of given', async () => {
        let response = await tester.invoke({
            url: 'https://example.com?v={event.properties.$lib_version}',
            debug: true,
        })

        expect(response.error).toBeUndefined()
        expect(response.logs).toMatchInlineSnapshot(`
            Array [
              Object {
                "level": "debug",
                "message": "Executing function",
                "timestamp": "2025-01-01T00:00:00.000+00:00",
              },
              Object {
                "level": "debug",
                "message": "Suspending function due to async function call 'fetch'. Payload: 3001 bytes. Event: event-id",
                "timestamp": "2025-01-01T00:00:00.000+00:00",
              },
            ]
        `)

        response = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: '{"message": "Hello, world!"}',
        })

        expect(response.error).toBeUndefined()
        expect(response.logs).toMatchInlineSnapshot(`
            Array [
              Object {
                "level": "debug",
                "message": "Resuming function",
                "timestamp": "2025-01-01T00:00:00.000+00:00",
              },
              Object {
                "level": "debug",
                "message": "Function completed in 0ms. Sync: 0ms. Mem: 1480 bytes. Ops: 28. Event: 'https://us.posthog.com/projects/1/events/1234'",
                "timestamp": "2025-01-01T00:00:00.000+00:00",
              },
            ]
        `)
    })
})
