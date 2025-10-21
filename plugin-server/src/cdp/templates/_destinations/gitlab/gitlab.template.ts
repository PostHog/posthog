import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-gitlab',
    name: 'GitLab',
    description: 'Creates an issue in a GitLab project',
    icon_url: '/static/services/gitlab.png',
    category: ['Error tracking'],
    code_language: 'hog',
    code: `let url := f'https://api.airtable.com/v0/{inputs.base_id}/{inputs.table_name}'

let payload := {
  'headers': {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {inputs.access_token}'
  },
  'body': {
    'fields': inputs.fields,
    'typecast': true
  },
  'method': 'POST'
}

if (inputs.debug) {
  print('Request', url, payload)
}

let res := fetch(url, payload);

if (inputs.debug) {
  print('Response', res.status, res.body);
}
if (res.status >= 400) {
    throw Error(f'Error from api.airtable.com (status {res.status}): {res.body}')
}`,
    inputs_schema: [
        {
            key: 'access_token',
            type: 'string',
            label: 'GitLab project access token',
            secret: true,
            required: true,
            description: 'Create this at https://airtable.com/create/tokens',
        },
        {
            key: 'team',
            type: 'integration_field',
            integration_key: 'linear_workspace',
            integration_field: 'linear_team',
            label: 'Team',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'title',
            type: 'string',
            label: 'Title',
            secret: false,
            hidden: false,
            required: true,
            default: '{event.properties.$exception_types[1]}',
        },
        {
            key: 'description',
            type: 'string',
            label: 'Description',
            secret: false,
            hidden: false,
            required: true,
            default: '{event.properties.$exception_values[1]}',
        },
        {
            key: 'posthog_issue_id',
            type: 'string',
            label: 'PostHog issue ID',
            secret: false,
            hidden: true,
            required: true,
            default: '{event.properties.$exception_issue_id}',
        },
    ],
}
