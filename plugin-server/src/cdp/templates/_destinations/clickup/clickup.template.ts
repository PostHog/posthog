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
  'headers': {
    'Authorization': 'Bearer ' + inputs.oauth.access_token,
    'Content-Type': 'application/json',
  },
  'body': {
    'name': inputs.taskName,
    'description': inputs.taskDescription,
    'assignees': inputs.assignees,
    'tags': inputs.tags,
    'due_date': inputs.dueDate,
    'status': inputs.status,
  },
  'method': 'POST'
}

let res := fetch('https://api.clickup.com/api/v2/list/{list_id}/task', payload);

if (res.status >= 400) {
    throw Error(f'Error from api.clickup.com (status {res.status}): {res.body}')
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
        {
            key: 'statusId',
            type: 'string',
            label: 'Status ID',
            description: 'ID of the ClickUp status to create the task in.',
            secret: false,
            required: false,
        },
        {
            key: 'assigneeId',
            type: 'string',
            label: 'Assignee ID',
            description: 'ID of the ClickUp assignee to assign the task to.',
            secret: false,
            required: false,
        },
        {
            key: 'description',
            type: 'string',
            label: 'Description',
            description: 'Description of the ClickUp task.',
            secret: false,
            required: false,
        },
    ],
}
