import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-llm-summarize.template'

describe('posthog-llm-summarize template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        // Gateway URL + auth are resolved server-side; deterministic test values so we can assert
        // they're not leaking to user-facing inputs and are routed via the workflows product path.
        tester.setHubConfig({
            LLM_GATEWAY_URL: 'http://gateway.test',
            LLM_GATEWAY_API_KEY: 'service-key',
        })
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    const baseInputs = {
        model: 'gpt-5-mini',
        instructions: 'Summarize the support ticket.',
        content: 'My invoice is wrong this month and I would like a refund please.',
    }

    it('does not expose gateway URL or API key as user-facing inputs', () => {
        const keys = template.inputs_schema.map((field) => field.key)
        expect(keys).not.toContain('api_key')
        expect(keys).not.toContain('gateway_url')
        expect(keys).not.toContain('user_distinct_id')
        // The user-meaningful inputs the form should expose. Unlike classify there is no
        // `categories` toggle — summarize is always structured into title + description.
        expect(keys).toEqual(expect.arrayContaining(['model', 'instructions', 'content']))
        expect(keys).not.toContain('categories')
    })

    it('builds a structured-output request enforcing { title, description }', async () => {
        const response = await tester.invoke(baseInputs)

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const params = response.invocation.queueParameters as Record<string, any>
        // Routed through the workflows product path on the configured gateway, with service auth
        // — never the user-provided URL/key.
        expect(params.url).toBe('http://gateway.test/workflows/v1/chat/completions')
        expect(params.method).toBe('POST')
        expect(params.headers).toEqual({
            Authorization: 'Bearer service-key',
            'Content-Type': 'application/json',
        })
        expect(params.timeout_ms).toBe(120_000)

        const body = parseJSON(params.body)
        expect(body.model).toBe('gpt-5-mini')
        expect(body.messages).toEqual([
            { role: 'system', content: 'Summarize the support ticket.' },
            { role: 'user', content: 'My invoice is wrong this month and I would like a refund please.' },
        ])
        expect(body.response_format.type).toBe('json_schema')
        expect(body.response_format.json_schema.name).toBe('summary')
        expect(body.response_format.json_schema.strict).toBe(true)
        expect(body.response_format.json_schema.schema.required).toEqual(['title', 'description'])
        expect(body.response_format.json_schema.schema.properties.title.type).toBe('string')
        expect(body.response_format.json_schema.schema.properties.description.type).toBe('string')
        expect(body.response_format.json_schema.schema.additionalProperties).toBe(false)
    })

    it('parses the { title, description } payload from a successful response', async () => {
        const initial = await tester.invoke(baseInputs)

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 200,
            body: {
                choices: [
                    {
                        message: {
                            content: JSON.stringify({
                                title: 'Incorrect invoice',
                                description: 'Customer reports a billing error and wants a refund.',
                            }),
                        },
                    },
                ],
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({
            title: 'Incorrect invoice',
            description: 'Customer reports a billing error and wants a refund.',
        })
    })

    it('omits the instructions message when instructions are blank', async () => {
        const response = await tester.invoke({ ...baseInputs, instructions: '' })

        const body = parseJSON((response.invocation.queueParameters as Record<string, any>).body)
        expect(body.messages).toEqual([{ role: 'user', content: baseInputs.content }])
        // Structured output is still enforced.
        expect(body.response_format.json_schema.name).toBe('summary')
    })

    it('throws when content is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, content: '' })

        expect(response.error).toMatch(/Content to summarize is required/)
    })

    it('throws when model is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, model: '' })

        expect(response.error).toMatch(/Model is required/)
    })

    it('throws when the gateway is not configured', async () => {
        tester.setHubConfig({ LLM_GATEWAY_URL: '', LLM_GATEWAY_API_KEY: '' })

        const response = await tester.invoke(baseInputs)

        expect(response.error).toMatch(/PostHog LLM gateway URL is not configured/)
    })

    it('throws on a gateway error response', async () => {
        const initial = await tester.invoke(baseInputs)

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 401,
            body: { error: 'invalid api key' },
        })

        expect(response.error).toMatch(/LLM summarization failed with status 401/)
    })
})
