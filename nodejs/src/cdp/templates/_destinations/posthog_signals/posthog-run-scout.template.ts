import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-run-scout',
    name: 'Run scout',
    description:
        'Start a Signals scout run from a workflow. The scout explores as it does on its schedule and files what it finds to your inbox. The triggering event starts the run but is not shown to it.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.skill_name)) {
  throw Error('A scout is required')
}

let response := postHogRunScout({ 'skill_name': inputs.skill_name })

if (response.status == 409) {
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
                'Name of the scout to run, as shown in your scout fleet, for example signals-scout-error-tracking. The scout must be active. A paused scout is skipped.',
        },
        {
            // The engine treats a 4xx as a step failure before the code above runs, unless the
            // status is listed here. 409 is the endpoint's answer for every kind of backpressure
            // (paused, in flight, cooldown, budget, quota), which the code above turns into a
            // graceful skip. A missing or unrunnable scout answers 404, deliberately NOT listed
            // here, so a misconfigured node fails loudly.
            key: 'non_failure_status_codes',
            type: 'non_failure_status_codes',
            label: 'Non-failure status codes',
            secret: false,
            required: false,
            hidden: true,
            default: [409],
        },
    ],
}
