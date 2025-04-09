import { HogFunctionTemplate, SUB_TEMPLATE_COMMON } from '../../types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    free: false,
    type: 'destination',
    id: 'template-linear',
    name: 'Linear',
    description: 'Creates an issue for a Linear team',
    icon_url: '/static/services/linear.png',
    category: ['Error tracking'],
    hog: `
let description :=f'{event.properties.description}

[View Person in PostHog]({person.url})
[Message source]({source.url})'

let mutation := f'mutation IssueCreate \{ issueCreate(input: \{ title: "{inputs.title}" description: "{description}" teamId: "{inputs.team}" }) \{ success issue \{ id } } }';

let res := fetch('https://api.linear.app/graphql', {
  'body': {
    'query': mutation,
  },
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.linear_workspace.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status != 200 or res.body.success == false) {
  throw Error(f'Failed to create Linear issue: {res.status}: {res.body}');
}`,
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
            default: '[PostHog Issue] {event.properties.name}',
            secret: false,
            required: true,
            hidden: true,
        },
        {
            key: 'description',
            type: 'string',
            label: 'Description',
            default: '{event.properties.description}',
            secret: false,
            required: true,
            hidden: true,
        },
    ],
    sub_templates: [
        {
            ...SUB_TEMPLATE_COMMON['error-tracking-issue-created'],
            name: 'Linear issue on issue created',
            description: 'Create an issue in Linear when an issue is created.',
        },
    ],
}
