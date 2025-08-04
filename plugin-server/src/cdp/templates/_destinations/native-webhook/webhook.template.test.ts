import { SAMPLE_GLOBALS } from '~/cdp/_tests/fixtures'

import { NATIVE_HOG_FUNCTIONS_BY_ID } from '../../index'
import { DestinationTester, generateTestData } from '../../test/test-helpers'

const template = NATIVE_HOG_FUNCTIONS_BY_ID['native-webhook']

describe(`${template.name} template`, () => {
    const tester = new DestinationTester(template!)

    beforeEach(() => {
        tester.beforeEach()
    })

    afterEach(() => {
        tester.afterEach()
    })

    it('should work with default mapping', async () => {
        const payload = {
            url: 'https://example.com/webhook',
            method: 'POST',
            body: { event: '{event}', person: '{person}' },
            headers: { 'Content-Type': 'application/json' },
            debug_mode: true,
        }
        const response = await tester.invoke(SAMPLE_GLOBALS, payload)

        expect(response.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "debug",
                "message": "config, {"method":"POST","body":{"event":{"uuid":"uuid","event":"test","distinct_id":"distinct_id","properties":{"email":"test@posthog.com"},"timestamp":"","elements_chain":"","url":""},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}},"headers":{"Content-Type":"application/json"},"debug":false,"debug_mode":true,"url":"https://example.com/webhook"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "endpoint, https://example.com/webhook",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "options, {"method":"POST","headers":{"Content-Type":"application/json"},"json":{"event":{"uuid":"uuid","event":"test","distinct_id":"distinct_id","properties":{"email":"test@posthog.com"},"timestamp":"","elements_chain":"","url":""},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}}}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "fetchOptions, {"method":"POST","headers":{"User-Agent":"PostHog.com/1.0","Content-Type":"application/json"},"body":"{\\"event\\":{\\"uuid\\":\\"uuid\\",\\"event\\":\\"test\\",\\"distinct_id\\":\\"distinct_id\\",\\"properties\\":{\\"email\\":\\"test@posthog.com\\"},\\"timestamp\\":\\"\\",\\"elements_chain\\":\\"\\",\\"url\\":\\"\\"},\\"person\\":{\\"id\\":\\"person-id\\",\\"name\\":\\"person-name\\",\\"properties\\":{\\"email\\":\\"example@posthog.com\\"},\\"url\\":\\"https://us.posthog.com/projects/1/persons/1234\\"}}"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "convertedResponse, 200, {"status":"OK"}, {"status":"OK"}, {"content-type":"application/json"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "info",
                "message": "Function completed in [REPLACED]",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
    })

    it('should handle a failing request', async () => {
        const inputs = generateTestData(template.id, template.inputs_schema)

        tester.mockFetchResponse({
            status: 400,
            body: { status: 'ERROR' },
            headers: { 'content-type': 'application/json' },
        })

        const response = await tester.invoke(SAMPLE_GLOBALS, { ...inputs, debug_mode: true })

        expect(response.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "debug",
                "message": "config, {"method":"POST","body":{"event":{"uuid":"uuid","event":"test","distinct_id":"distinct_id","properties":{"email":"test@posthog.com"},"timestamp":"","elements_chain":"","url":""},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}},"headers":{"Content-Type":"application/json"},"debug":false,"debug_mode":true,"url":"http://jaj.mu/iroti"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "endpoint, http://jaj.mu/iroti",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "options, {"method":"POST","headers":{"Content-Type":"application/json"},"json":{"event":{"uuid":"uuid","event":"test","distinct_id":"distinct_id","properties":{"email":"test@posthog.com"},"timestamp":"","elements_chain":"","url":""},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}}}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "fetchOptions, {"method":"POST","headers":{"User-Agent":"PostHog.com/1.0","Content-Type":"application/json"},"body":"{\\"event\\":{\\"uuid\\":\\"uuid\\",\\"event\\":\\"test\\",\\"distinct_id\\":\\"distinct_id\\",\\"properties\\":{\\"email\\":\\"test@posthog.com\\"},\\"timestamp\\":\\"\\",\\"elements_chain\\":\\"\\",\\"url\\":\\"\\"},\\"person\\":{\\"id\\":\\"person-id\\",\\"name\\":\\"person-name\\",\\"properties\\":{\\"email\\":\\"example@posthog.com\\"},\\"url\\":\\"https://us.posthog.com/projects/1/persons/1234\\"}}"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "warn",
                "message": "HTTP request failed with status 400 ({"status":"ERROR"}). ",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "error",
                "message": "Function failed: Error executing function on event uuid: Request failed with status 400 ({"status":"ERROR"})",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
    })
})
