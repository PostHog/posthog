import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-llm-extract.template'

describe('posthog-llm-extract template', () => {
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
        instructions: 'Extract structured info from this support ticket.',
        content: 'My invoice is wrong and I need help urgently!',
        fields: {
            sentiment: 'How the user feels.',
            urgency: 'How urgent the issue is.',
        },
    }

    it('does not expose gateway URL or API key as user-facing inputs', () => {
        const keys = template.inputs_schema.map((field) => field.key)
        expect(keys).not.toContain('api_key')
        expect(keys).not.toContain('gateway_url')
        expect(keys).not.toContain('user_distinct_id')
        // The user-meaningful inputs the form should expose:
        expect(keys).toEqual(expect.arrayContaining(['model', 'instructions', 'content', 'fields']))
        // Categories belongs to classify, not extract — extract uses the generic `fields` dict.
        expect(keys).not.toContain('categories')
    })

    it('builds a structured-output request from the fields dictionary', async () => {
        const response = await tester.invoke(baseInputs)

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)

        const params = response.invocation.queueParameters as Record<string, any>
        // Routed through the workflows product path on the configured gateway with service auth.
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
            { role: 'system', content: 'Extract structured info from this support ticket.' },
            { role: 'user', content: 'My invoice is wrong and I need help urgently!' },
        ])

        const schema = body.response_format.json_schema
        expect(body.response_format.type).toBe('json_schema')
        expect(schema.name).toBe('extraction')
        expect(schema.strict).toBe(true)
        expect(schema.schema.additionalProperties).toBe(false)
        // Both user-defined fields are required so the model addresses each one even
        // when null. Strict mode requires every property to be listed in `required`.
        expect(schema.schema.required.sort()).toEqual(['sentiment', 'urgency'])
        // Each field is nullable so partial extraction is well-formed.
        expect(schema.schema.properties.sentiment).toEqual({
            type: ['string', 'null'],
            description: 'How the user feels.',
        })
        expect(schema.schema.properties.urgency).toEqual({
            type: ['string', 'null'],
            description: 'How urgent the issue is.',
        })
    })

    it('parses the extracted fields from a successful response', async () => {
        const initial = await tester.invoke(baseInputs)

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 200,
            body: {
                choices: [
                    {
                        message: {
                            content: JSON.stringify({
                                sentiment: 'frustrated',
                                urgency: 'high',
                            }),
                        },
                    },
                ],
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({
            sentiment: 'frustrated',
            urgency: 'high',
        })
    })

    it('preserves nulls when the model cannot determine a field', async () => {
        const initial = await tester.invoke(baseInputs)

        const response = await tester.invokeFetchResponse(initial.invocation, {
            status: 200,
            body: {
                choices: [
                    {
                        message: {
                            content: JSON.stringify({
                                sentiment: 'frustrated',
                                urgency: null,
                            }),
                        },
                    },
                ],
            },
        })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        // null passes through so downstream `extracted.urgency != null` checks work.
        expect(response.execResult).toEqual({
            sentiment: 'frustrated',
            urgency: null,
        })
    })

    it('omits the instructions message when instructions are blank', async () => {
        const response = await tester.invoke({ ...baseInputs, instructions: '' })

        const body = parseJSON((response.invocation.queueParameters as Record<string, any>).body)
        expect(body.messages).toEqual([{ role: 'user', content: baseInputs.content }])
        // Structured output is still enforced.
        expect(body.response_format.json_schema.name).toBe('extraction')
    })

    it('throws when content is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, content: '' })

        expect(response.error).toMatch(/Content to extract from is required/)
    })

    it('throws when model is missing', async () => {
        const response = await tester.invoke({ ...baseInputs, model: '' })

        expect(response.error).toMatch(/Model is required/)
    })

    it('throws when no fields are configured', async () => {
        const response = await tester.invoke({ ...baseInputs, fields: {} })

        expect(response.error).toMatch(/At least one field to extract is required/)
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

        expect(response.error).toMatch(/LLM extraction failed with status 401/)
    })

    it('skips the LLM call and returns sampled_out when sample_rate is 0', async () => {
        // sample_rate='0' deterministically samples out (bucket >= 0 is always true).
        // Asserts no fetch was dispatched and the action returned the stable
        // { sampled_out: true } shape downstream conditional_branch can read.
        const response = await tester.invoke({ ...baseInputs, sample_rate: '0' })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.execResult).toEqual({ sampled_out: true })
    })

    it('runs normally when sample_rate is 1.0', async () => {
        const response = await tester.invoke({ ...baseInputs, sample_rate: '1.0' })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(false)
        expect((response.invocation.queueParameters as Record<string, any>).url).toBe(
            'http://gateway.test/workflows/v1/chat/completions'
        )
    })
})
