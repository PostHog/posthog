import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-hide-survey',
    name: 'Hide survey',
    description:
        'Stop showing an in-app survey to this person. Use it after they answer, or when you stop waiting for an answer.',
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

postHogCapture({
  'event': '$set',
  'distinct_id': inputs.distinct_id,
  'properties': {
    '$unset': [f'$survey_triggered/{inputs.survey_id}']
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
            description: 'The survey to stop showing. Use the same survey as the "Show survey" step.',
        },
        {
            type: 'string',
            key: 'distinct_id',
            label: 'Distinct ID',
            required: true,
            secret: false,
            hidden: true,
            default: '{event.distinct_id}',
            description: 'The distinct ID of the person to stop showing the survey to.',
        },
    ],
}
