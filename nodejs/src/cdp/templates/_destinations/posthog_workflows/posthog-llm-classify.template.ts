import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-llm-classify',
    name: 'LLM classify',
    description: 'Classify the triggering event with an LLM and write the result to a workflow variable',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'AI'],
    code_language: 'hog',
    code: `
if (empty(inputs.api_key)) {
  throw Error('PostHog personal API key with llm_gateway:read scope is required')
}
if (empty(inputs.model)) {
  throw Error('Model is required')
}
if (empty(inputs.user_content)) {
  throw Error('User content is required')
}

let messages := []
if (not empty(inputs.system_prompt)) {
  messages := arrayPushBack(messages, {'role': 'system', 'content': inputs.system_prompt})
}
messages := arrayPushBack(messages, {'role': 'user', 'content': inputs.user_content})

let body := {
  'model': inputs.model,
  'messages': messages
}

if (not empty(inputs.user_distinct_id)) {
  body.user := inputs.user_distinct_id
}

// Tag-list shorthand: turn 'billing, support, sales' into a structured-output schema
// that forces the model to pick exactly one tag plus a short reasoning. The parsed
// JSON ({ category, reasoning }) flows straight into the workflow variable so
// downstream conditional_branch steps can route on classification.category.
let tags := arrayFilter(x -> not empty(x), arrayMap(x -> trim(x), splitByString(',', inputs.tags ?? '')))
if (length(tags) > 0) {
  body.response_format := {
    'type': 'json_schema',
    'json_schema': {
      'name': 'classification',
      'strict': true,
      'schema': {
        'type': 'object',
        'additionalProperties': false,
        'required': ['category', 'reasoning'],
        'properties': {
          'category': {'type': 'string', 'enum': tags},
          'reasoning': {'type': 'string'}
        }
      }
    }
  }
}

let res := fetch(inputs.gateway_url, {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.api_key}',
    'Content-Type': 'application/json'
  },
  'body': body
})

if (res.status >= 400) {
  throw Error(f'LLM gateway returned status {res.status}: {res.body}')
}

let choices := res.body.choices
if (empty(choices)) {
  throw Error('LLM gateway returned no choices')
}

let content := choices[1].message.content

// Parse the structured output when a tag list was configured. Free-form
// responses pass through as { content: '...' } so the workflow variable
// always has a stable shape.
if (length(tags) > 0) {
  return jsonParse(content)
}

return {'content': content}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'PostHog API key',
            secret: true,
            required: true,
            description:
                'PostHog personal API key with the `llm_gateway:read` scope. Create one at /settings/user-api-keys.',
        },
        {
            key: 'model',
            type: 'string',
            label: 'Model',
            secret: false,
            required: true,
            default: 'gpt-5-mini',
            description: 'Any model supported by the PostHog LLM gateway (OpenAI, Anthropic, OpenRouter, Fireworks).',
        },
        {
            key: 'system_prompt',
            type: 'string',
            label: 'System prompt',
            secret: false,
            required: false,
            description: 'Instructions for the model. Templated against the trigger event.',
        },
        {
            key: 'user_content',
            type: 'string',
            label: 'User content',
            secret: false,
            required: true,
            default: '{event.event}: {jsonStringify(event.properties)}',
            description: 'The content the model should classify. Templated against the trigger event.',
        },
        {
            key: 'tags',
            type: 'string',
            label: 'Tag list',
            secret: false,
            required: false,
            description:
                'Optional comma-separated tag list (e.g. `billing, support, sales`). When set, the model picks one via structured outputs and the result is parsed as `{ category, reasoning }`. Leave empty for free-form completions.',
        },
        {
            key: 'user_distinct_id',
            type: 'string',
            label: 'End-user distinct ID',
            secret: false,
            required: false,
            default: '{event.distinct_id}',
            description: 'Passed to the gateway as `user` for per-end-user analytics and rate limiting.',
        },
        {
            key: 'gateway_url',
            type: 'string',
            label: 'LLM gateway URL',
            secret: false,
            required: true,
            default: 'https://gateway.us.posthog.com/v1/chat/completions',
            description: 'Override for EU (`https://gateway.eu.posthog.com/v1/chat/completions`) or self-hosted.',
        },
    ],
}
