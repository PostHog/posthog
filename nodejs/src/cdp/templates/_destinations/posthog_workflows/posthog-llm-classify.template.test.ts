import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-llm-classify.template'

describe('posthog-llm-classify template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    const baseInputs = {
        api_key: 'phx_test_key',
        model: 'gpt-5-mini',
        system_prompt: 'You classify support tickets.',
        user_content: 'My invoice is wrong',
        user_distinct_id: 'distinct-id',
        gateway_url: 'https://gateway.us.posthog.com/v1/chat/completions',
    }

    it('builds a structured-output request when tags are provided', async () => {
        const response = await tester.invoke({
            ...baseInputs,
            tags: 'billing, support, sales',
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const params = response.invocation.queueParameters as Record<string, any>
        expect(params.url).toBe('https://gateway.us.posthog.com/v1/chat/completions')
        expect(params.method).toBe('POST')
        expect(params.headers).toEqual({
            Authorization: 'Bearer phx_test_key',
            'Content-Type': 'application/json',
        })

        const body = parseJSON(params.body)
        expect(body.model).toBe('gpt-5-mini')
        expect(body.user).toBe('distinct-id')
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
            tags: 'billing, support, sales',
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

    it('omits response_format and returns free-form content when tags are empty', async () => {
        const initial = await tester.invoke({ ...baseInputs, tags: '' })

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

    it('drops empty entries from the tag list', async () => {
        const response = await tester.invoke({
            ...baseInputs,
            // Trailing comma + extra whitespace would otherwise produce empty enum values, which
            // OpenAI's structured-output validator rejects with an opaque 400.
            tags: 'billing, , support,  ',
        })

        const body = parseJSON((response.invocation.queueParameters as Record<string, any>).body)
        expect(body.response_format.json_schema.schema.properties.category.enum).toEqual(['billing', 'support'])
    })

    it('throws when api_key is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, api_key: '' })

        expect(response.error).toMatch(/PostHog personal API key/)
    })

    it('throws when user_content is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, user_content: '' })

        expect(response.error).toMatch(/User content is required/)
    })

    it('throws on a gateway error response', async () => {
        const initial = await tester.invoke({ ...baseInputs, tags: 'a, b' })

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 401,
            body: { error: 'invalid api key' },
        })

        expect(response.error).toMatch(/LLM gateway returned status 401/)
    })
})
