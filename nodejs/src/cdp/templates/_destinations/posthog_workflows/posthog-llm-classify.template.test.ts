import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-llm-classify.template'

describe('posthog-llm-classify template', () => {
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
        instructions: 'You classify support tickets.',
        content: 'My invoice is wrong',
    }

    it('does not expose gateway URL or API key as user-facing inputs', () => {
        const keys = template.inputs_schema.map((field) => field.key)
        expect(keys).not.toContain('api_key')
        expect(keys).not.toContain('gateway_url')
        expect(keys).not.toContain('user_distinct_id')
        // The user-meaningful inputs the form should expose:
        expect(keys).toEqual(expect.arrayContaining(['model', 'instructions', 'content', 'categories']))
    })

    it('builds a structured-output request when categories are provided', async () => {
        const response = await tester.invoke({
            ...baseInputs,
            categories: 'billing, support, sales',
        })

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

        const body = parseJSON(params.body)
        expect(body.model).toBe('gpt-5-mini')
        expect(body.messages).toEqual([
            { role: 'system', content: 'You classify support tickets.' },
            { role: 'user', content: 'My invoice is wrong' },
        ])
        expect(body.response_format.type).toBe('json_schema')
        expect(body.response_format.json_schema.name).toBe('classification')
        expect(body.response_format.json_schema.strict).toBe(true)
        expect(body.response_format.json_schema.schema.properties.category.enum).toEqual([
            'billing',
            'support',
            'sales',
        ])
        expect(body.response_format.json_schema.schema.required).toEqual(['category', 'reasoning'])
    })

    it('parses the structured-output content on successful response', async () => {
        const initial = await tester.invoke({
            ...baseInputs,
            categories: 'billing, support, sales',
        })

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 200,
            body: {
                choices: [
                    {
                        message: {
                            content: JSON.stringify({
                                category: 'billing',
                                reasoning: 'mentioned invoice',
                            }),
                        },
                    },
                ],
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({
            category: 'billing',
            reasoning: 'mentioned invoice',
        })
    })

    it('omits response_format and returns free-form content when categories are empty', async () => {
        const initial = await tester.invoke({ ...baseInputs, categories: '' })

        const body = parseJSON((initial.invocation.queueParameters as Record<string, any>).body)
        expect(body.response_format).toBeUndefined()

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 200,
            body: {
                choices: [{ message: { content: 'free-form classification' } }],
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({ content: 'free-form classification' })
    })

    it('drops empty entries from the categories list', async () => {
        const response = await tester.invoke({
            ...baseInputs,
            // Trailing comma + extra whitespace would otherwise produce empty enum values, which
            // OpenAI's structured-output validator rejects with an opaque 400.
            categories: 'billing, , support,  ',
        })

        const body = parseJSON((response.invocation.queueParameters as Record<string, any>).body)
        expect(body.response_format.json_schema.schema.properties.category.enum).toEqual(['billing', 'support'])
    })

    it('throws when content is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, content: '' })

        expect(response.error).toMatch(/Content to classify is required/)
    })

    it('throws when model is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, model: '' })

        expect(response.error).toMatch(/Model is required/)
    })

    it('throws when the gateway is not configured', async () => {
        tester.setHubConfig({ LLM_GATEWAY_URL: '', LLM_GATEWAY_API_KEY: '' })

        const response = await tester.invoke({ ...baseInputs, categories: 'a, b' })

        expect(response.error).toMatch(/PostHog LLM gateway URL is not configured/)
    })

    it('throws on a gateway error response', async () => {
        const initial = await tester.invoke({ ...baseInputs, categories: 'a, b' })

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 401,
            body: { error: 'invalid api key' },
        })

        expect(response.error).toMatch(/LLM classification failed with status 401/)
    })
})
