import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'stable',
    free: false,
    type: 'destination',
    id: 'template-linear',
    name: 'Linear',
    description: 'Creates an issue for a Linear team',
    icon_url: '/static/services/linear.png',
    category: ['Error tracking'],
    code_language: 'hog',
    code: `fun query(mutation) {
    return fetch('https://api.linear.app/graphql', {
        'body': {
            'query': mutation,
        },
        'method': 'POST',
        'headers': {
            'Authorization': f'Bearer {inputs.linear_workspace.access_token}',
            'Content-Type': 'application/json'
        }
    })
}

let issue_mutation := f'mutation IssueCreate \\{ issueCreate(input: \\{ title: "{inputs.title}" description: "{inputs.description}" teamId: "{inputs.team}" }) \\{ success issue \\{ identifier } } }';

let issue_response := query(issue_mutation);

if (issue_response.status != 200) {
  throw Error(f'Failed to post create issue in Linear: {issue_response.status}: {issue_response.body}');
}

let linear_issue_id := issue_response.body.data.issueCreate.issue.identifier;

let attachment_url := f'{project.url}/error_tracking/{inputs.posthog_issue_id}';
let attachment_mutation := f'mutation AttachmentCreate \\{ attachmentCreate(input: \\{ issueId: "{linear_issue_id}", title: "PostHog issue", url: "{attachment_url}" }) \\{ success } }';

query(attachment_mutation);`,
    inputs_schema: [
        {
            key: 'linear_workspace',
            type: 'integration',
            integration: 'linear',
            label: 'Linear workspace',
            secret: false,
            hidden: false,
            required: true,
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
