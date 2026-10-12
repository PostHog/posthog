import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-replay-vision-analyze-sessions',
    name: 'Analyze sessions with Replay vision',
    description:
        "Have Replay vision watch the triggering event's session recording and answer a question about it. The step waits for the answer, then passes it to the next step.",
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.session_id)) {
  throw Error('The triggering event has no session recording to analyze')
}

if (empty(inputs.scanner_id) and empty(inputs.prompt)) {
  throw Error('A question or a scanner is required')
}

let payload := { 'session_ids': [inputs.session_id], 'wait_for_session_end': inputs.wait_for_session_end != false }
if (not empty(inputs.scanner_id)) {
  payload.scanner_id := inputs.scanner_id
} else {
  payload.prompt := inputs.prompt
}

let response := postHogAnalyzeSessions(payload)

if (response.status >= 400) {
  throw Error(f'Failed to start the Replay vision scan ({response.status}): {apiErrorMessage(response)}')
}

let scan := response.body
if (scan.status == 'running') {
  // Park the step until the scan settles: up to 6 hours for the session to end, the scan itself, and slack for the wake.
  scan.await := { 'max_wait': '8h', 'label': 'Replay vision scan' }
}
return scan
`,
    inputs_schema: [
        {
            key: 'session_id',
            type: 'string',
            label: 'Session ID',
            secret: false,
            required: true,
            default: '{event.properties.$session_id}',
            description: 'The session recording to analyze. Defaults to the triggering event’s session.',
        },
        {
            key: 'wait_for_session_end',
            type: 'boolean',
            label: 'Wait for the session to end',
            secret: false,
            required: false,
            default: true,
            description:
                'Scan the recording once the session has been quiet for 35 minutes, so the whole session is analyzed. Turn this off only when the triggering event comes after the session is over.',
        },
        {
            key: 'prompt',
            type: 'string',
            label: 'Question',
            secret: false,
            required: false,
            description: 'What to look for in the recording, in plain language. Ignored when a scanner is set.',
        },
        {
            key: 'scanner_id',
            type: 'replay_vision_scanner',
            label: 'Scanner',
            secret: false,
            required: false,
            description: 'A saved scanner to analyze the recording with. Leave empty to ask the question instead.',
        },
    ],
}
