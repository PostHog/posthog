import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-run-scout',
    name: 'Run scout',
    description:
        'Start a Signals scout run from a workflow. The scout explores exactly as it does on its schedule and files what it finds to your inbox — the triggering event starts the run but is not shown to it.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.skill_name)) {
  throw Error('A scout is required')
}

let response := postHogRunScout({ 'skill_name': inputs.skill_name })

if (response.status == 409 or response.status == 429) {
  print(f'Scout not run: {apiErrorMessage(response)}')
  return { 'skipped': true, 'reason': apiErrorMessage(response) }
}

if (response.status >= 400) {
  throw Error(f'Failed to run scout ({response.status}): {apiErrorMessage(response)}')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'skill_name',
            type: 'string',
            label: 'Scout',
            secret: false,
            required: true,
            description:
                'Name of the scout to run, as shown in your scout fleet (e.g. signals-scout-error-tracking). The scout must be active — a paused scout is skipped.',
        },
        {
            // The engine treats a 4xx as a step failure before the code above runs, unless the
            // status is listed here. Both of these are ordinary backpressure the code turns into a
            // graceful skip: 409 is "a run for this scout is already in flight" (or the scout is
            // paused), 429 is the 30-minute workflow cooldown, the project's daily run budget, or
            // its Signals quota. A missing or unrunnable scout is deliberately NOT listed — that's
            // a misconfigured node, and it should fail loudly.
            key: 'non_failure_status_codes',
            type: 'non_failure_status_codes',
            label: 'Non-failure status codes',
            secret: false,
            required: false,
            hidden: true,
            default: [409, 429],
        },
    ],
}
