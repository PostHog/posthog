import { createPromptConfig } from './llmPlaygroundPromptsLogic'
import { parsePlaygroundConfig, serializePlaygroundConfig } from './playgroundPromptConfig'

describe('playgroundPromptConfig', () => {
    const modelConfig = { model: 'gpt-5', provider: 'openai', provider_key_id: 'key-1' }
    const responseSchema = { type: 'object', properties: { ok: { type: 'boolean' } }, required: ['ok'] }
    const responseFormat = {
        type: 'json_schema' as const,
        json_schema: { name: 'verdict', schema: responseSchema, strict: false },
    }
    const fullPrompt = createPromptConfig({
        model: 'gpt-5',
        selectedProviderKeyId: 'key-1',
        systemPrompt: 'You help {{customer}}.',
        maxTokens: 1024,
        temperature: 0.7,
        topP: 0.9,
        thinking: true,
        reasoningLevel: 'high',
        tools: [{ type: 'function', function: { name: 'lookup' } }],
        responseFormat,
        messages: [
            { role: 'user', content: 'Hi {{name}}' },
            {
                role: 'assistant',
                content: 'Hello!',
                toolCalls: [{ id: 'call_1', name: 'lookup', arguments: '{"q": "x"}' }],
            },
            { role: 'tool', content: '{"rows": 2}', toolCallId: 'call_1', toolName: 'lookup' },
        ],
    })

    it('round-trips the full panel state through serialize and parse', () => {
        const parsed = parsePlaygroundConfig(serializePlaygroundConfig(fullPrompt, modelConfig, null))
        expect(parsed).toEqual({
            model: 'gpt-5',
            provider: 'openai',
            providerKeyId: 'key-1',
            temperature: 0.7,
            maxTokens: 1024,
            topP: 0.9,
            thinking: true,
            reasoningLevel: 'high',
            tools: [{ type: 'function', function: { name: 'lookup' } }],
            responseFormat,
            messages: [
                { role: 'user', content: 'Hi {{name}}' },
                {
                    role: 'assistant',
                    content: 'Hello!',
                    toolCalls: [{ id: 'call_1', name: 'lookup', arguments: '{"q": "x"}' }],
                },
                { role: 'tool', content: '{"rows": 2}', toolCallId: 'call_1', toolName: 'lookup' },
            ],
        })
    })

    it('round-trips a default panel without inventing values', () => {
        const serialized = serializePlaygroundConfig(createPromptConfig(), modelConfig, null)
        expect(Object.keys(serialized ?? {})).toEqual(
            expect.not.arrayContaining(['temperature', 'max_tokens', 'top_p', 'tools', 'response_format', 'messages'])
        )
        expect(parsePlaygroundConfig(serialized)).toMatchObject({
            temperature: null,
            maxTokens: null,
            topP: null,
            thinking: false,
            reasoningLevel: 'medium',
            tools: null,
            responseFormat: null,
            messages: [],
        })
    })

    it('preserves config keys it does not own across a save', () => {
        const existing = { model: 'api-model', custom_pipeline: { stage: 2 }, owner: 'api-user' }
        const serialized = serializePlaygroundConfig(fullPrompt, modelConfig, existing)
        expect(serialized).toMatchObject({
            custom_pipeline: { stage: 2 },
            owner: 'api-user',
            model: 'gpt-5',
        })
    })

    it.each([
        [
            'keeps a stored format the playground cannot edit',
            { type: 'json_object' },
            createPromptConfig(),
            { type: 'json_object' },
        ],
        ['replaces it once the panel has a schema', { type: 'json_object' }, fullPrompt, responseFormat],
        ['drops a supported format the user cleared', responseFormat, createPromptConfig(), undefined],
    ])('%s when saving over an existing response format', (_, existing, prompt, expected) => {
        const serialized = serializePlaygroundConfig(prompt, modelConfig, { response_format: existing })
        expect(serialized?.response_format).toEqual(expected)
    })

    it('carries the stored model selection forward when no model config is passed', () => {
        const existing = { model: 'gpt-5', provider: 'openai', provider_key_id: 'key-1', owner: 'api-user' }
        const serialized = serializePlaygroundConfig(createPromptConfig(), null, existing)
        expect(serialized).toMatchObject({
            model: 'gpt-5',
            provider: 'openai',
            provider_key_id: 'key-1',
            owner: 'api-user',
        })
    })

    it('omits an unknown provider but keeps the model id when options have not loaded', () => {
        const parsed = parsePlaygroundConfig(
            serializePlaygroundConfig(
                fullPrompt,
                { model: 'acme/custom', provider: '', provider_key_id: 'key-9' },
                null
            )
        )
        expect(parsed).toMatchObject({ model: 'acme/custom', provider: null, providerKeyId: 'key-9' })
    })

    it.each([null, undefined, 'a plain string prompt config', 42, [], { unrelated_key: true }])(
        'leaves the panel untouched for configs without playground keys: %p',
        (config) => {
            expect(parsePlaygroundConfig(config)).toBeNull()
        }
    )

    it('ignores wrong-typed values instead of corrupting the panel', () => {
        const parsed = parsePlaygroundConfig({
            model: 5,
            temperature: 'hot',
            max_tokens: NaN,
            thinking: 'yes',
            reasoning_effort: 'extreme',
            tools: ['not-an-object'],
            response_format: { type: 'json_object' },
            messages: [{ role: 'alien', content: 'x' }, { role: 'user', content: 'ok' }, 'junk'],
        })
        expect(parsed).toEqual({
            model: null,
            provider: null,
            providerKeyId: null,
            temperature: null,
            maxTokens: null,
            topP: null,
            thinking: false,
            reasoningLevel: null,
            tools: null,
            responseFormat: null,
            messages: [{ role: 'user', content: 'ok' }],
        })
    })

    it.each([
        [
            'fills in the name and strict flag',
            { type: 'json_schema', json_schema: { schema: responseSchema } },
            { type: 'json_schema', json_schema: { name: 'response', schema: responseSchema, strict: true } },
        ],
        [
            'drops a format whose schema is not an object',
            { type: 'json_schema', json_schema: { schema: 'object' } },
            null,
        ],
    ])('%s when restoring a response format written outside the playground', (_, stored, expected) => {
        expect(parsePlaygroundConfig({ response_format: stored })?.responseFormat).toEqual(expected)
    })
})
