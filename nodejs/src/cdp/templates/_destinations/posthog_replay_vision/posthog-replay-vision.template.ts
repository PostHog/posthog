import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-replay-vision',
    name: 'Replay Vision',
    description:
        "Have Replay Vision watch the triggering event's session recording: answer a question, categorize, score or summarize it. The step waits for the answer, then passes it to the next step.",
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.session_id)) {
  throw Error('The triggering event has no session recording to analyze')
}

let response := postHogReplayVisionScan({
  'session_id': inputs.session_id,
  'setup': inputs.analysis,
  'wait_for_session_end': inputs.wait_for_session_end != false
})

// A daily scan limit skips this event instead of failing the run.
if (response.status == 409) {
  print(apiErrorMessage(response))
  return { 'state': 'skipped', 'output': null, 'warnings': [apiErrorMessage(response)] }
}

if (response.status >= 400) {
  throw Error(f'Failed to start the Replay Vision scan ({response.status}): {apiErrorMessage(response)}')
}

let scan := response.body
// Park the step until the scan settles: up to 6 hours for the session to end, the scan itself, and slack for the wake.
let wait := { 'max_wait': '8h', 'label': 'Replay Vision scan' }
if (scan.status != 'running') {
  // An answer already settled goes through the same sizing a wake gets.
  wait.result := { 'state': scan.state, 'output': scan.output, 'warnings': scan.warnings }
}
return { 'request_id': scan.request_id, 'await': wait }
`,
    inputs_schema: [
        {
            key: 'analysis',
            type: 'replay_vision_scan',
            label: 'What should Replay Vision do?',
            secret: false,
            required: true,
            default: { type: 'monitor', prompt: '' },
            description: 'Ask a question, categorize, score or summarize the session, or use a saved scanner.',
        },
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
            // The engine fails the step on a 4xx before the code above sees it, unless the status is listed here.
            // 409 is the daily scan limit, which the code turns into a skip. Required, though hidden, so a step
            // built through the API or MCP gets the default too (see the run-scout template).
            key: 'non_failure_status_codes',
            type: 'non_failure_status_codes',
            label: 'Non-failure status codes',
            secret: false,
            required: true,
            hidden: true,
            default: [409],
        },
    ],
}
