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

// Probabilistic sampling — when sample_rate < 1, skip the LLM call on (1 - sample_rate)
// of triggered events. Bucket is derived from sha256(event.uuid) so the decision is
// deterministic per event (cyclotron retries on the same event get the same answer)
// but pseudo-random across events. Returns a stable { sampled_out: true } shape so
// downstream conditional_branch can read classification.sampled_out and route.
let sample := toFloat(inputs.sample_rate)
if (sample != null and sample < 1) {
  let bucket := toInt(concat('0x', substring(sha256Hex(event.uuid), 1, 4)))
  if (bucket >= sample * 65536) {
    return {'sampled_out': true}
  }
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

let res := postHogLLMChatCompletion(request)

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
            default: 'gpt-5.4-nano',
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
        {
            key: 'sample_rate',
            type: 'string',
            label: 'Sample rate',
            secret: false,
            required: false,
            default: '1.0',
            description:
                'Probability that this action runs on a triggered event (0.0 to 1.0). Default 1.0 runs every time. Use 0.1 to sample 10% of triggered events — handy for keeping LLM costs bounded on high-volume triggers. When sampled out, the action returns `{ sampled_out: true }` so downstream `conditional_branch` steps can detect and route accordingly. The decision is deterministic per event (derived from `sha256(event.uuid)`), so retries on the same event always make the same choice.',
        },
    ],
}
