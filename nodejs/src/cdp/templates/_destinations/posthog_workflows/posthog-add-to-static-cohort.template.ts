import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-add-to-static-cohort',
    name: 'Add to static cohort',
    description: 'Add the person to a static cohort.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

let response := postHogAddToStaticCohort({
  'cohort_id': inputs.cohort_id,
  'person_uuid': person.id
})

if (response.status >= 400) {
  throw Error(f'Could not add the person to the static cohort ({response.status}): {apiErrorMessage(response)}')
}

print(response.body.detail)
`,
    inputs_schema: [
        {
            key: 'cohort_id',
            type: 'number',
            label: 'Static cohort',
            required: true,
            // The callback compares this value with the cohorts the saved workflow names, so it can't be a template.
            templating: false,
            description: 'The static cohort to add the person to.',
        },
    ],
}
