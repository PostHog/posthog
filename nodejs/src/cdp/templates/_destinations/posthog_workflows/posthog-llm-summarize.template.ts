import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-llm-summarize',
    name: 'LLM summarize',
    description: 'Summarize the triggering event with an LLM into a title and description for downstream steps',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'AI'],
    code_language: 'hog',
    code: `
if (empty(inputs.model)) {
  throw Error('Model is required')
}
if (empty(inputs.content)) {
  throw Error('Content to summarize is required')
}

// Probabilistic sampling — when sample_rate < 1, skip the LLM call on (1 - sample_rate)
// of triggered events. Bucket is derived from sha256(event.uuid) so the decision is
// deterministic per event (cyclotron retries on the same event get the same answer)
// but pseudo-random across events. Returns a stable { sampled_out: true } shape so
// downstream conditional_branch can read summary.sampled_out and route.
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

// Always force a structured { title, description } output so downstream steps can read
// summary.title / summary.description without having to parse a free-form response.
let request := {
  'model': inputs.model,
  'messages': messages,
  'response_format': {
    'type': 'json_schema',
    'json_schema': {
      'name': 'summary',
      'strict': true,
      'schema': {
        'type': 'object',
        'additionalProperties': false,
        'required': ['title', 'description'],
        'properties': {
          'title': {'type': 'string'},
          'description': {'type': 'string'}
        }
      }
    }
  }
}

let res := postHogLLMChatCompletion(request)

if (res.status >= 400) {
  throw Error(f'LLM summarization failed with status {res.status}: {res.body}')
}

let choices := res.body.choices
if (empty(choices)) {
  throw Error('LLM summarization returned no choices')
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
                'Summarize the content below. Return a short title (under 80 chars) and a 1-2 sentence description.',
            description:
                'What the model should do. Example: "Summarize the support ticket below for a triage queue. Title should name the problem; description should give just enough context for routing."',
        },
        {
            key: 'content',
            type: 'string',
            label: 'Content to summarize',
            secret: false,
            required: true,
            default: '{event.event}: {jsonStringify(event.properties)}',
            description: 'The data the model should look at. Templated against the trigger event.',
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
