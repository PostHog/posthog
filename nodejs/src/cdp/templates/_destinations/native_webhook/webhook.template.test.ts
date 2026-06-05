import '~/tests/helpers/mocks/date.mock'
import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { NATIVE_HOG_FUNCTIONS_BY_ID } from '../../index'
import { TemplateTester, generateTestData } from '../../test/test-helpers'

const template = NATIVE_HOG_FUNCTIONS_BY_ID['native-webhook']
describe(`${template.name} template`, () => {
    const tester = new TemplateTester({ ...template, code: '', code_language: 'javascript' })
    beforeEach(async () => {
        await tester.beforeEach()
        mockFetch.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ status: 'OK' }),
            text: () => Promise.resolve(JSON.stringify({ status: 'OK' })),
            headers: { 'content-type': 'application/json' },
            dump: () => Promise.resolve(),
        })
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
        const response = await tester.invoke({ ...payload })
        expect(tester.logsForSnapshot(response.logs)).toMatchInlineSnapshot(
            `
            [
              {
                "level": "debug",
                "message": "config, {"method":"POST","body":{"event":{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$current_url":"https://example.com"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}},"headers":{"Content-Type":"application/json"},"debug":false,"debug_mode":true,"url":"https://example.com/webhook"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "endpoint, https://example.com/webhook",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "options, {"method":"POST","headers":{"Content-Type":"application/json"},"json":{"event":{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$current_url":"https://example.com"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}}}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "fetchOptions, {"method":"POST","headers":{"User-Agent":"PostHog.com/1.0","Content-Type":"application/json"},"body":"{\\"event\\":{\\"uuid\\":\\"event-id\\",\\"event\\":\\"event-name\\",\\"distinct_id\\":\\"distinct-id\\",\\"properties\\":{\\"$current_url\\":\\"https://example.com\\"},\\"timestamp\\":\\"2024-01-01T00:00:00Z\\",\\"elements_chain\\":\\"\\",\\"url\\":\\"https://us.posthog.com/projects/1/events/1234\\"},\\"person\\":{\\"id\\":\\"person-id\\",\\"name\\":\\"person-name\\",\\"properties\\":{\\"email\\":\\"example@posthog.com\\"},\\"url\\":\\"https://us.posthog.com/projects/1/persons/1234\\"}}"}",
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
        `
        )
    })
    it('should handle a failing request', async () => {
        const inputs = generateTestData(template.id, template.inputs_schema)
        mockFetch.mockResolvedValue({
            status: 400,
            json: () => Promise.resolve({ status: 'ERROR' }),
            text: () => Promise.resolve(JSON.stringify({ status: 'ERROR' })),
            headers: { 'content-type': 'application/json' },
            dump: () => Promise.resolve(),
        })
        const response = await tester.invoke({ ...inputs, debug_mode: true })
        expect(response.logs).toMatchInlineSnapshot(
            `
            [
              {
                "level": "debug",
                "message": "config, {"method":"POST","body":{"event":{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$current_url":"https://example.com"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}},"headers":{"Content-Type":"application/json"},"debug":false,"debug_mode":true,"url":"http://jaj.mu/iroti"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "endpoint, http://jaj.mu/iroti",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "options, {"method":"POST","headers":{"Content-Type":"application/json"},"json":{"event":{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$current_url":"https://example.com"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}}}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "debug",
                "message": "fetchOptions, {"method":"POST","headers":{"User-Agent":"PostHog.com/1.0","Content-Type":"application/json"},"body":"{\\"event\\":{\\"uuid\\":\\"event-id\\",\\"event\\":\\"event-name\\",\\"distinct_id\\":\\"distinct-id\\",\\"properties\\":{\\"$current_url\\":\\"https://example.com\\"},\\"timestamp\\":\\"2024-01-01T00:00:00Z\\",\\"elements_chain\\":\\"\\",\\"url\\":\\"https://us.posthog.com/projects/1/events/1234\\"},\\"person\\":{\\"id\\":\\"person-id\\",\\"name\\":\\"person-name\\",\\"properties\\":{\\"email\\":\\"example@posthog.com\\"},\\"url\\":\\"https://us.posthog.com/projects/1/persons/1234\\"}}"}",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "warn",
                "message": "HTTP request failed with status 400 ({"status":"ERROR"}). ",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
              {
                "level": "error",
                "message": "Function failed: Error executing function on event event-id: Request failed with status 400 ({"status":"ERROR"})",
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `
        )
    })
})
