import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-http-request',
    name: 'HTTP request',
    description:
        'Call a URL and store whether the response matched what you expected. The step does not fail when the request fails, so you can branch on the result.',
    icon_url: '/static/services/webhook.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
fun statusMatches(status, expected) {
  for (let part in splitByString(',', expected)) {
    let code := lower(trim(part))
    if (code like '_xx') {
      if (toString(floor(status / 100)) == substring(code, 1, 1)) {
        return true
      }
    } else if (toString(status) == code) {
      return true
    }
  }
  return false
}

let method := upper(inputs.method ?? 'GET')
let expected := inputs.expected_status
if (empty(expected)) {
  expected := '2xx,3xx'
}

// One attempt only: the result must describe this request, not a retried one.
let payload := {
  'method': method,
  'max_tries': 1,
  'fail_on_error': false
}
if (not empty(inputs.headers)) {
  payload['headers'] := inputs.headers
}
if (not empty(inputs.body)) {
  payload['body'] := inputs.body
}
if (not empty(inputs.timeout_ms)) {
  payload['timeout_ms'] := toInt(inputs.timeout_ms)
}

let res := fetch(inputs.url, payload)

let status := res.status
let text := res.body ?? ''
if (typeof(text) != 'string') {
  text := jsonStringify(text)
}

let ok := false
let error := null
if (not empty(res.error)) {
  status := 0
  text := ''
  error := res.error
} else if (not statusMatches(status, expected)) {
  error := f'Expected status {expected} but got {status}'
} else if (not empty(inputs.body_contains) and position(text, inputs.body_contains) == 0) {
  error := f'The response body does not contain "{inputs.body_contains}"'
} else {
  ok := true
}

return {
  'ok': ok,
  'status': status,
  'duration_ms': res.duration_ms,
  'error': error,
  'body': substring(text, 1, 1000)
}
`,
    inputs_schema: [
        {
            key: 'url',
            type: 'string',
            label: 'URL',
            secret: false,
            required: true,
            description: 'The URL to call.',
        },
        {
            key: 'method',
            type: 'choice',
            label: 'Method',
            secret: false,
            choices: ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'].map((value) => ({ label: value, value })),
            default: 'GET',
            required: false,
            description: 'The HTTP method to use.',
        },
        {
            key: 'headers',
            type: 'dictionary',
            label: 'Headers',
            secret: false,
            required: false,
            description: 'HTTP headers to send with the request.',
        },
        {
            key: 'body',
            type: 'json',
            label: 'JSON body',
            secret: false,
            required: false,
            description: 'The request body. GET and HEAD requests send no body.',
        },
        {
            key: 'timeout_ms',
            type: 'number',
            label: 'Timeout (ms)',
            secret: false,
            required: false,
            description: 'How long to wait for a response, up to 10000 ms.',
        },
        {
            key: 'expected_status',
            type: 'string',
            label: 'Expected status',
            secret: false,
            required: false,
            default: '2xx,3xx',
            description:
                'Status codes that count as a success, separated by commas. Use ranges like 2xx or exact codes like 200,204.',
        },
        {
            key: 'body_contains',
            type: 'string',
            label: 'Body contains',
            secret: false,
            required: false,
            description: 'Text the response body must contain to count as a success.',
        },
    ],
}
