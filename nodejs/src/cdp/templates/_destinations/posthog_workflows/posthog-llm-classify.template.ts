import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-llm-classify',
    name: 'LLM classify',
    description: 'Classify the triggering event with an LLM and store the result for downstream branches',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'AI'],
    code_language: 'hog',
    code: `
if (empty(inputs.model)) {
  throw Error('Model is required')
}
if (empty(inputs.content)) {
  throw Error('Content to classify is required')
}

let messages := []
if (not empty(inputs.instructions)) {
  messages := arrayPushBack(messages, {'role': 'system', 'content': inputs.instructions})
}
messages := arrayPushBack(messages, {'role': 'user', 'content': inputs.content})

let request := {
  'model': inputs.model,
  'messages': messages
}

// Categories shorthand: turn 'billing, support, sales' into a structured-output schema
// that forces the model to pick exactly one tag plus a short reasoning. The parsed
// JSON ({ category, reasoning }) flows straight into the workflow variable so
// downstream conditional_branch steps can route on classification.category.
let categories := arrayFilter(x -> not empty(x), arrayMap(x -> trim(x), splitByString(',', inputs.categories ?? '')))
if (length(categories) > 0) {
  request.response_format := {
    'type': 'json_schema',
    'json_schema': {
      'name': 'classification',
      'strict': true,
      'schema': {
        'type': 'object',
        'additionalProperties': false,
        'required': ['category', 'reasoning'],
        'properties': {
          'category': {'type': 'string', 'enum': categories},
          'reasoning': {'type': 'string'}
        }
      }
    }
  }
}

let res := postHogLLMClassify(request)

if (res.status >= 400) {
  throw Error(f'LLM classification failed with status {res.status}: {res.body}')
}

let choices := res.body.choices
if (empty(choices)) {
  throw Error('LLM classification returned no choices')
}

let content := choices[1].message.content

// Parse the structured output when categories were configured. Free-form
// responses pass through as { content: '...' } so the workflow variable
// always has a stable shape.
if (length(categories) > 0) {
  return jsonParse(content)
}

return {'content': content}
`,
    inputs_schema: [
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
            key: 'instructions',
            type: 'string',
            label: 'Instructions',
            secret: false,
            required: false,
            description:
                'What the model should do. Example: "Classify the support ticket below into one of the listed categories. Pick the best fit even if uncertain."',
        },
        {
            key: 'content',
            type: 'string',
            label: 'Content to classify',
            secret: false,
            required: true,
            default: '{event.event}: {jsonStringify(event.properties)}',
            description: 'The data the model should look at. Templated against the trigger event.',
        },
        {
            key: 'categories',
            type: 'string',
            label: 'Categories',
            secret: false,
            required: false,
            description:
                'Optional comma-separated list (e.g. `billing, support, sales`). When set, the model picks exactly one and the result is parsed as `{ category, reasoning }`. Leave empty for free-form classification — the result is parsed as `{ content }`.',
        },
    ],
}
