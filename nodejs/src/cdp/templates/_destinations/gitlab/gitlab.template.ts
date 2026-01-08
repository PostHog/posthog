import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'alpha',
    free: false,
    type: 'destination',
    id: 'template-gitlab',
    name: 'GitLab',
    description: 'Creates an issue in a GitLab project',
    icon_url: '/static/services/gitlab.png',
    category: ['Error tracking'],
    code_language: 'hog',
    code: `let posthog_issue_url := f'{project.url}/error_tracking/{inputs.posthog_issue_id}'
let payload := {
    'method': 'POST',
    'headers': {
        'PRIVATE-TOKEN': inputs.gitlab_project.access_token,
    },
    'body': {
        'title': inputs.title,
        'body': f'{inputs.description}\n\n[View in PostHog]({posthog_issue_url})'
    }
}

let res := fetch(f'{inputs.gitlab_project.hostname}/api/v4/projects/{inputs.gitlab_project.project_id}/issues', payload)
if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to create GitLab issue: {res.status}: {res.body}')
}`,
    inputs_schema: [
        {
            key: 'gitlab_project',
            type: 'integration',
            integration: 'gitlab',
            label: 'GitLab project',
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
