import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'beta',
    type: 'destination',
    id: 'template-clickup',
    name: 'ClickUp',
    description: 'Create ClickUp tasks from event data',
    icon_url: '/static/services/clickup.svg',
    category: ['Productivity'],
    code_language: 'hog',
    code: `
let payload := {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
}

let res := fetch('https://webhook.site/6ba37b29-6706-4cd5-8e1a-7a4cb73e680f', payload);

if (res.status >= 400) {
  throw Error(f'Webhook failed with status {res.status}: {res.body}');
} else {
  print('response', res.body)
}
`,
    inputs_schema: [
        {
            key: 'oauth',
            type: 'integration',
            integration: 'clickup',
            label: 'ClickUp account',
            requiredScopes: 'https://www.googleapis.com/auth/adwords https://www.googleapis.com/auth/userinfo.email',
            secret: false,
            required: true,
        },
        {
            key: 'workspaceId',
            type: 'integration_field',
            integration_key: 'oauth',
            integration_field: 'clickup_workspace_id',
            label: 'Workspace ID',
            description: 'ID of the ClickUp workspace.',
            secret: false,
            required: true,
        },
        {
            key: 'spaceId',
            type: 'integration_field',
            integration_key: 'oauth',
            integration_field: 'clickup_space_id',
            requires_field: 'workspaceId',
            label: 'Space ID',
            description: 'ID of the ClickUp space.',
            secret: false,
            required: true,
        },
        {
            key: 'listId',
            type: 'integration_field',
            integration_key: 'oauth',
            integration_field: 'clickup_list_id',
            requires_field: 'spaceId',
            label: 'List ID',
            description: 'ID of the ClickUp list.',
            secret: false,
            required: true,
        },
        {
            key: 'taskName',
            type: 'string',
            label: 'Task Name',
            description: 'Name of the ClickUp task to create.',
            secret: false,
            required: true,
        },
    ],
}
