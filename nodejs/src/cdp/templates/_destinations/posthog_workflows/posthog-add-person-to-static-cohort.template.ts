import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-add-person-to-static-cohort',
    name: 'Add person to static cohort',
    description: 'Add the workflow person to an existing static cohort.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

let response := postHogAddPersonToStaticCohort({
  'cohort_id': inputs.cohort_id,
  'person_uuid': person.id
})

if (response.status >= 400) {
  throw Error(f'Could not update static cohort ({response.status}): {apiErrorMessage(response)}')
}

print(response.body.detail)
return response.body
`,
    inputs_schema: [
        {
            key: 'cohort_id',
            type: 'number',
            label: 'Static cohort',
            required: true,
            description: 'The static cohort to add this person to.',
        },
    ],
}
