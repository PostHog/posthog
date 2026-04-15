import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-llm-completion',
    name: 'Call LLM',
    description: 'Make an LLM completion request using your own API key',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.provider_key_id)) {
  throw Error('Provider key is required')
}
if (empty(inputs.provider)) {
  throw Error('Provider is required')
}
if (empty(inputs.model)) {
  throw Error('Model is required')
}

let opts := {
  'provider_key_id': inputs.provider_key_id,
  'provider': inputs.provider,
  'model': inputs.model,
  'messages': inputs.messages
}

if (not empty(inputs.system_prompt)) {
  opts.system := inputs.system_prompt
}
if (inputs.temperature != null) {
  opts.temperature := inputs.temperature
}
if (inputs.max_tokens != null) {
  opts.max_tokens := inputs.max_tokens
}

let response := postHogLLMCompletion(opts)

if (response.status >= 400) {
  throw Error(f'LLM request failed with status {response.status}: {response.body}')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'provider_key_id',
            type: 'llm_provider_key',
            label: 'API key',
            secret: false,
            required: true,
            description: 'Select an LLM provider key configured in your project settings.',
            templating: false,
        },
        {
            key: 'provider',
            type: 'choice',
            label: 'Provider',
            secret: false,
            required: true,
            choices: [
                { label: 'OpenAI', value: 'openai' },
                { label: 'Anthropic', value: 'anthropic' },
                { label: 'Google Gemini', value: 'gemini' },
                { label: 'OpenRouter', value: 'openrouter' },
                { label: 'Fireworks', value: 'fireworks' },
            ],
            description: 'The LLM provider to use.',
            templating: false,
        },
        {
            key: 'model',
            type: 'string',
            label: 'Model',
            secret: false,
            required: true,
            default: 'gpt-4o-mini',
            description: 'The model identifier (e.g., gpt-4o-mini, claude-sonnet-4-20250514).',
        },
        {
            key: 'system_prompt',
            type: 'string',
            label: 'System prompt',
            secret: false,
            required: false,
            description: 'Optional system prompt. Supports Hog templating with {event}, {person}, {variables}.',
        },
        {
            key: 'messages',
            type: 'json',
            label: 'Messages',
            secret: false,
            required: true,
            default: [{ role: 'user', content: 'Hello' }],
            description: 'Array of message objects with role and content fields. Supports Hog templating.',
        },
        {
            key: 'temperature',
            type: 'number',
            label: 'Temperature',
            secret: false,
            required: false,
            description: 'Sampling temperature (0-2). Lower values are more deterministic.',
        },
        {
            key: 'max_tokens',
            type: 'number',
            label: 'Max tokens',
            secret: false,
            required: false,
            description: 'Maximum number of tokens in the response.',
        },
    ],
}
