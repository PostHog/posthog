import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'stable',
    free: false,
    type: 'destination',
    id: 'template-github',
    name: 'GitHub',
    description: 'Creates an issue in a GitHub repository',
    icon_url: '/static/services/github.png',
    category: ['Error tracking'],
    code_language: 'hog',
    code: `let owner := inputs.github_installation.account.name
let repo := inputs.repository

if (not owner) {
    throw Error('Owner is required')
}

if (not repo) {
    throw Error('Repository is required')
}

let posthog_issue_url := f'{project.url}/error_tracking/{inputs.posthog_issue_id}'
let payload := {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.github_installation.access_token}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'PostHog Github App'
    },
    'body': {
        'title': inputs.title,
        'body': f'{inputs.description}\n\n[View in PostHog]({posthog_issue_url})'
    }
}

let res := fetch(f'https://api.github.com/repos/{owner}/{repo}/issues', payload)
if (res.status < 200 or res.status >= 300) {
    throw Error(f'Failed to create GitHub issue: {res.status}: {res.body}')
}`,
    inputs_schema: [
        {
            key: 'github_installation',
            type: 'integration',
            integration: 'github',
            label: 'GitHub installation',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'repository',
            type: 'integration_field',
            integration_key: 'github_installation',
            integration_field: 'github_repository',
            label: 'Repository',
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
