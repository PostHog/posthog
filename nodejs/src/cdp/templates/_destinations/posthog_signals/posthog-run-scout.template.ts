import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-run-scout',
    name: 'Run scout',
    description:
        'Start a Signals scout run from a workflow. The scout explores as it does on its schedule and files what it finds to your inbox. Add a note to tell the scout what triggered the run.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.skill_name)) {
  throw Error('A scout is required')
}

let response := postHogRunScout({ 'skill_name': inputs.skill_name, 'note': inputs.note, 'when_busy': inputs.when_busy })

if (response.status == 409) {
  print(f'Scout not run: {apiErrorMessage(response)}')
  return { 'skipped': true, 'reason': apiErrorMessage(response) }
}

if (response.status >= 400) {
  throw Error(f'Failed to run scout ({response.status}): {apiErrorMessage(response)}')
}

let run := response.body
if (run.queued) {
  print('Scout busy: the trigger is queued, and a later run handles it')
  return { 'skipped': false, 'queued': true, 'scout': run.scout }
}
if (not empty(run.workflow_id)) {
  // Park the workflow step until the run finishes: the scout runtime cap plus slack for its wake.
  run.await := { 'max_wait': '35m', 'label': 'scout run' }
}
return run
`,
    inputs_schema: [
        {
            key: 'skill_name',
            type: 'signals_scout',
            label: 'Scout',
            secret: false,
            required: true,
            description:
                'Name of the scout to run, as shown in your scout fleet, for example signals-scout-error-tracking. The scout must be active. A paused scout is skipped.',
        },
        {
            key: 'note',
            type: 'string',
            label: 'Note',
            secret: false,
            required: false,
            description:
                'Optional. Tells the scout what triggered this run, so it can focus on it. Use identifiers such as a PR number or URL, for example PR #{event.properties.pr_number}, not free text like a title or body from the event. The scout sees the note for this run only. Notes longer than 1,000 characters are cut. Adding a note requires editor access to skills.',
        },
        {
            // Hidden like the status codes below: queueing is the default, and an author who only
            // wants the latest event to count sets "skip" through the API or MCP. Not required, so
            // a step saved before this input existed sends nothing and queues.
            key: 'when_busy',
            type: 'choice',
            label: 'When the scout is busy',
            secret: false,
            required: false,
            hidden: true,
            templating: false,
            choices: [
                { label: 'Queue the trigger', value: 'queue' },
                { label: 'Skip it', value: 'skip' },
            ],
            default: 'queue',
            description:
                'What happens when the scout is already running, or ran from a workflow in the last 30 minutes. Queue the trigger, and a later run handles its note. Or skip it.',
        },
        {
            // The engine treats a 4xx as a step failure before the code above runs, unless the
            // status is listed here. 409 is the endpoint's answer for every kind of backpressure
            // (paused, budget, quota, and a busy scout when `when_busy` is "skip"), which the code
            // above turns into a graceful skip.
            // A missing or unrunnable scout answers 404, deliberately NOT listed here, so a
            // misconfigured node fails loudly.
            // required (despite being hidden): the backend only fills a schema default for a
            // required input (products/cdp/backend/validation.py), and an API- or MCP-built step has no
            // editor to pre-fill this from the template, so it would otherwise publish with the
            // field unset and fail its workflow on ordinary backpressure instead of skipping.
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
