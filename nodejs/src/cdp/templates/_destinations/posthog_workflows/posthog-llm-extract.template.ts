import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-llm-extract',
    name: 'LLM extract',
    description:
        'Extract one or more structured fields from the triggering event with an LLM and store them for downstream steps',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'AI'],
    code_language: 'hog',
    code: `
if (empty(inputs.model)) {
  throw Error('Model is required')
}
if (empty(inputs.content)) {
  throw Error('Content to extract from is required')
}

// Probabilistic sampling — when sample_rate < 1, skip the LLM call on (1 - sample_rate)
// of triggered events. Bucket is derived from sha256(event.uuid) so the decision is
// deterministic per event (cyclotron retries on the same event get the same answer)
// but pseudo-random across events. Returns a stable { sampled_out: true } shape so
// downstream conditional_branch can read extracted.sampled_out and route.
let sample := toFloat(inputs.sample_rate)
if (sample != null and sample < 1) {
  let bucket := toInt(concat('0x', substring(sha256Hex(event.uuid), 1, 4)))
  if (bucket >= sample * 65536) {
    return {'sampled_out': true}
  }
}

// Build the structured-output schema from inputs.fields. The dictionary key becomes
// the JSON Schema property name (and the downstream workflow variable name); the
// dictionary value is the description the model uses to know what to extract. Every
// field is required and nullable so the model has to address each one — null when it
// cannot determine a value — which keeps the downstream variable shape stable across
// extraction quality, so conditional_branch steps never see a missing key.
let properties := {}
let required := []
for (let name, description in inputs.fields ?? {}) {
  if (empty(name)) {
    continue
  }
  properties[name] := {
    'type': ['string', 'null'],
    'description': description
  }
  required := arrayPushBack(required, name)
}

if (length(required) == 0) {
  throw Error('At least one field to extract is required')
}

let messages := []
if (not empty(inputs.instructions)) {
  messages := arrayPushBack(messages, {'role': 'system', 'content': inputs.instructions})
}
messages := arrayPushBack(messages, {'role': 'user', 'content': inputs.content})

let request := {
  'model': inputs.model,
  'messages': messages,
  'response_format': {
    'type': 'json_schema',
    'json_schema': {
      'name': 'extraction',
      'strict': true,
      'schema': {
        'type': 'object',
        'additionalProperties': false,
        'required': required,
        'properties': properties
      }
    }
  }
}

let res := postHogLLMChatCompletion(request)

if (res.status >= 400) {
  throw Error(f'LLM extraction failed with status {res.status}: {res.body}')
}

let choices := res.body.choices
if (empty(choices)) {
  throw Error('LLM extraction returned no choices')
}

return jsonParse(choices[1].message.content)
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
            default:
                'Extract the requested fields from the content below. Be concise — single values or short phrases. Return null for any field you cannot confidently determine from the content rather than guessing.',
            description:
                'What the model should do. Example: "Extract structured info from this support ticket. Be conservative: return null when uncertain."',
        },
        {
            key: 'content',
            type: 'string',
            label: 'Content to extract from',
            secret: false,
            required: true,
            default: '{event.event}: {jsonStringify(event.properties)}',
            description: 'The data the model should look at. Templated against the trigger event.',
        },
        {
            key: 'fields',
            type: 'dictionary',
            label: 'Fields to extract',
            secret: false,
            required: true,
            default: {
                sentiment: 'How the user feels about the issue (e.g. frustrated, neutral, satisfied).',
                intent: 'What action the user wants to happen.',
                urgency: 'How quickly this needs attention (e.g. low, medium, high).',
            },
            description:
                'Each entry defines one value to extract. The key is the field name (available downstream as `extracted.<name>`); the value is the description the model uses to know what to extract. Every field is nullable — the model returns null when it cannot determine a value, so downstream `conditional_branch` steps always see a stable shape.',
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
