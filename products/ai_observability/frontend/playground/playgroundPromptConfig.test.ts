import { createPromptConfig } from './llmPlaygroundPromptsLogic'
import { parsePlaygroundConfig, serializePlaygroundConfig } from './playgroundPromptConfig'

describe('playgroundPromptConfig', () => {
    const modelConfig = { model: 'gpt-5', provider: 'openai', provider_key_id: 'key-1' }
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
            expect.not.arrayContaining(['temperature', 'max_tokens', 'top_p', 'tools', 'messages'])
        )
        expect(parsePlaygroundConfig(serialized)).toMatchObject({
            temperature: null,
            maxTokens: null,
            topP: null,
            thinking: false,
            reasoningLevel: 'medium',
            tools: null,
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
            messages: [{ role: 'user', content: 'ok' }],
        })
    })
})
