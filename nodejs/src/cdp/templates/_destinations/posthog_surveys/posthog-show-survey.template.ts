import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-show-survey',
    name: 'Show survey',
    description:
        'Show an in-app survey to this person the next time they open your web or mobile app. The survey only appears to people a workflow has reached when its targeting includes the workflow condition.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.survey_id)) {
  throw Error('A survey is required')
}

if (empty(inputs.distinct_id)) {
  throw Error('Distinct ID is required')
}

// The survey's targeting flag matches on this person property, and the SDKs pick it up on their next flag refresh.
let props := {}
props[f'$survey_triggered/{inputs.survey_id}'] := true

postHogCapture({
  'event': '$set',
  'distinct_id': inputs.distinct_id,
  'properties': {
    '$set': props
  }
})
`,
    inputs_schema: [
        {
            key: 'survey_id',
            type: 'posthog_survey',
            label: 'Survey',
            secret: false,
            required: true,
            description: 'The in-app survey to show. Launch it and keep its targeting limited to workflow recipients.',
        },
        {
            type: 'string',
            key: 'distinct_id',
            label: 'Distinct ID',
            required: true,
            secret: false,
            hidden: true,
            default: '{event.distinct_id}',
            description: 'The distinct ID of the person to show the survey to.',
        },
    ],
}
