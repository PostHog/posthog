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
    code: `fun query(operation) {
    return fetch('https://api.linear.app/graphql', {
        'body': {
            'query': operation,
        },
        'method': 'POST',
        'headers': {
            'Authorization': f'Bearer {inputs.linear_workspace.access_token}',
            'Content-Type': 'application/json'
        }
    })
}

let attachment_url := f'{project.url}/error_tracking/{inputs.posthog_issue_id}';

// Deduplicate per PostHog error tracking issue. Every exception on the same issue
// triggers this destination, but we only want one Linear issue per PostHog issue.
// We link the Linear issue back to PostHog with an attachment carrying the issue URL,
// so we can ask Linear whether one already exists rather than keeping our own state.
if (notEmpty(inputs.posthog_issue_id)) {
    let existing_query := f'query AttachmentsForURL \\{ attachmentsForURL(url: {jsonStringify(attachment_url)}) \\{ nodes \\{ id } } }';
    let existing_response := query(existing_query);
    if (existing_response.status == 200 and notEmpty(existing_response.body.data.attachmentsForURL.nodes)) {
        print(f'A Linear issue already exists for PostHog issue {inputs.posthog_issue_id}, skipping creation.');
        return;
    }
}

let issue_mutation := f'mutation IssueCreate \\{ issueCreate(input: \\{ title: {jsonStringify(inputs.title)} description: {jsonStringify(inputs.description)} teamId: "{inputs.team}" }) \\{ success issue \\{ identifier } } }';

let issue_response := query(issue_mutation);

if (issue_response.status != 200) {
  throw Error(f'Failed to post create issue in Linear: {issue_response.status}: {issue_response.body}');
}

let linear_issue_id := issue_response.body.data.issueCreate.issue.identifier;

// Name the attachment after the originating PostHog project so a Linear workspace wired
// into several projects makes it obvious which project each issue came from.
let attachment_title := notEmpty(project.name) ? f'PostHog issue ({project.name})' : 'PostHog issue';
let attachment_mutation := f'mutation AttachmentCreate \\{ attachmentCreate(input: \\{ issueId: "{linear_issue_id}", title: {jsonStringify(attachment_title)}, url: "{attachment_url}" }) \\{ success } }';

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
