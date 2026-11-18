import { HogFunctionTemplate } from '~/cdp/types'

import { ERROR_TRACKING_TICKET_DESCRIPTION, ERROR_TRACKING_TICKET_TITLE } from '../../error-tracking-ticket'
import { hogErrorTrackingStacktraceFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    status: 'stable',
    free: false,
    type: 'destination',
    id: 'template-gitlab',
    name: 'GitLab',
    description: 'Creates an issue in a GitLab project',
    icon_url: '/static/services/gitlab.png',
    category: ['Error tracking'],
    code_language: 'hog',
    code: `${hogErrorTrackingStacktraceFn}

let posthog_issue_url := inputs.posthog_issue_url
if (empty(posthog_issue_url)) {
    posthog_issue_url := f'{project.url}/error-tracking/{inputs.posthog_issue_id}'
}
// GitLab links @mentions and URLs in an issue title, and notifies each mentioned user. Client-sent text
// in a code span stays plain text.
let title := notEmpty(inputs.title) ? concat('\`', replaceAll(replaceAll(inputs.title, '\`', '\\''), '\\n', ' '), '\`') : inputs.title
let payload := {
    'method': 'POST',
    'headers': {
        'PRIVATE-TOKEN': inputs.gitlab_project.access_token,
        'Content-Type': 'application/json'
    },
    'body': {
        'title': title,
        'description': f'{inputs.description}{errorTrackingStacktrace(event.properties.$exception_list)}\n\n[View in PostHog]({posthog_issue_url})'
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
            default: ERROR_TRACKING_TICKET_TITLE,
        },
        {
            key: 'description',
            type: 'string',
            label: 'Description',
            secret: false,
            hidden: false,
            required: true,
            default: ERROR_TRACKING_TICKET_DESCRIPTION,
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
        {
            key: 'posthog_issue_url',
            type: 'string',
            label: 'PostHog issue URL',
            description:
                'Link back to the PostHog issue. When empty, a link is built from the PostHog issue ID instead.',
            secret: false,
            hidden: true,
            required: false,
        },
    ],
}
